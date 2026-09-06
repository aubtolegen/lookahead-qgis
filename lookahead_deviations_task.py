import math
import logging
from collections import defaultdict
from qgis.core import (QgsTask, QgsGeometry, QgsPointXY, QgsPoint, Qgis, 
                       QgsFeatureRequest, QgsSpatialIndex, QgsWkbTypes, QgsFeature, 
                       QgsVectorLayer, QgsField, QgsFields, QgsProject,
                       QgsCoordinateReferenceSystem, NULL, QgsGeometryUtils,
                       QgsLineString, QgsLineSymbol, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory)
from qgis.PyQt.QtCore import QVariant
from .qt_compat import (
    swallow_exc,
    QGS_REQUEST_NO_GEOMETRY as _QGS_REQUEST_NO_GEOMETRY,
    QGS_REQUEST_NO_FLAGS as _QGS_REQUEST_NO_FLAGS,
    QGS_REQUEST_SUBSET_OF_ATTRIBUTES as _QGS_REQUEST_SUBSET_OF_ATTRIBUTES,
    QGS_TASK_CAN_CANCEL as _QGS_TASK_CAN_CANCEL,
    WKB_POLYGON,
    WKB_MULTIPOLYGON,
    WKB_LINE_GEOMETRY,
    WKB_POINT_GEOMETRY,
    WKB_POLYGON_GEOMETRY,
    WKB_LINESTRING,
    WKB_MULTILINESTRING,
)
from .lookahead_dockwidget_impl import UserCancelException, is_line_type

log = logging.getLogger(__name__)

GEOMETRY_PRECISION = 1e-6

class DeviationsTask(QgsTask):
    def __init__(self, description, lines_layer, nogo_layer, clearance_m, turn_radius_m, debug_mode, on_finished_callback):
        super().__init__(description, _QGS_TASK_CAN_CANCEL)
        self.lines_layer = lines_layer
        self.nogo_layer = nogo_layer
        self.clearance_m = clearance_m
        self.turn_radius_m = turn_radius_m
        self.debug_mode = debug_mode
        self.on_finished_callback = on_finished_callback
        
        self.attribute_changes = defaultdict(dict)
        self.deleted_fids = set()
        self.added_features = []
        
        self.dev_features = []
        self.dev_layer_name = None
        self.dev_fields = None
        self.dev_crs = None
        
        self.exception = None
        self.path_options = None
        self.chosen_paths = None
        self.success = False

    def run(self):
        try:
            self.success = self._calculate_and_apply_deviations_v2(self.lines_layer, self.nogo_layer, self.clearance_m, self.turn_radius_m, self.debug_mode)
            return True
        except Exception as e:
            self.exception = e
            log.exception(e)
            return False

    def finished(self, result):
        if self.on_finished_callback:
            self.on_finished_callback(self.exception, self.success, self.attribute_changes, self.deleted_fids, self.added_features, self.dev_features, self.path_options, self.chosen_paths)

    def _prepare_avoidance_geometry(self, nogo_layer, clearance_m, preserve_individual=False):
        """
        Prepares buffered geometry representing NoGo zones.
        Args:
            nogo_layer: The layer containing NoGo zones
            clearance_m: Buffer distance in meters
            preserve_individual: If True, returns a list of individual obstacle geometries;
                               If False, returns a single combined geometry (default behavior)
        Returns:
            If preserve_individual=False: QgsGeometry or None
            If preserve_individual=True: List of QgsGeometry objects or None
        """
        log.debug(f"Preparing NoGo geometry with clearance {clearance_m}m")
        if not nogo_layer or not nogo_layer.isValid():
            log.warning("No valid No-Go layer provided.")
            return None

        all_buffered_geoms = []
        processed_feats = 0
        invalid_input_feats = 0
        buffer_failures = 0
        feature_request = QgsFeatureRequest().setFlags(
            _QGS_REQUEST_NO_FLAGS)  # Need geometry

        # Progress for potentially long buffering
        progress = None
        pass
        pass

        try:
            for i, feat in enumerate(nogo_layer.getFeatures(feature_request)):
                if self.isCanceled():
                    raise UserCancelException("Buffering cancelled.")
                pass

                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    invalid_input_feats += 1
                    continue

                # Repair input geometry if necessary
                if not geom.isGeosValid():
                    log.debug(
                        f"Repairing invalid input geometry for feature {feat.id()}")
                    geom = self._repair_geometry(geom)
                    if not geom:
                        invalid_input_feats += 1
                        continue  # Repair failed

                # Apply buffer
                # 10 segments per quarter circle
                buffered_geom = geom.buffer(clearance_m, 10)

                if not buffered_geom or buffered_geom.isEmpty():
                    log.warning(f"Buffering failed for feature {feat.id()}")
                    buffer_failures += 1
                    continue

                # Repair buffered geometry if necessary
                if not buffered_geom.isGeosValid():
                    log.debug(
                        f"Repairing invalid buffered geometry for feature {feat.id()}")
                    buffered_geom = self._repair_geometry(buffered_geom)
                    if not buffered_geom:
                        buffer_failures += 1
                        continue  # Repair failed

                all_buffered_geoms.append(buffered_geom)
                processed_feats += 1

            pass

            if invalid_input_feats > 0:
                log.warning(
                    f"Skipped {invalid_input_feats} invalid input NoGo features.")
            if buffer_failures > 0:
                log.warning(
                    f"Encountered {buffer_failures} buffer/repair failures.")

            if not all_buffered_geoms:
                log.warning("No valid buffered NoGo geometries generated.")
                pass

                return None

            # Return individual geometries or combined geometry based on the preserve_individual flag
            if preserve_individual:
                # Return the list of individual buffered geometries
                if not all_buffered_geoms:
                    return None

                log.info(
                    f"Successfully prepared {len(all_buffered_geoms)} individual avoidance geometries from {processed_feats} features.")
                return all_buffered_geoms
            else:
                # Combine all buffered geometries using unaryUnion (original behavior)
                log.debug(
                    f"Combining {len(all_buffered_geoms)} buffered geometries...")
                pass
                if self.isCanceled(): return False  # Update UI

                final_avoidance_geom = QgsGeometry.unaryUnion(
                    all_buffered_geoms)

                if not final_avoidance_geom or final_avoidance_geom.isEmpty():
                    log.error("Failed to combine buffered NoGo zones.")
                    pass

                    return None

                # Final validation and repair
                if not final_avoidance_geom.isGeosValid():
                    log.warning(
                        "Combined avoidance geometry is invalid, attempting repair...")
                    final_avoidance_geom = self._repair_geometry(
                        final_avoidance_geom)
                    if not final_avoidance_geom:
                        log.error(
                            "Repair of combined avoidance geometry failed.")
                        pass

                        return None

                log.info(
                    f"Successfully prepared combined avoidance geometry from {processed_feats} features.")
                return final_avoidance_geom

        except Exception as e:
            log.exception(f"Error preparing NoGo avoidance geometry: {e}")
            pass

            return None
        finally:
            # Close progress dialog
            if False:
                pass



    def _separate_avoidance_geometry(self, geometry, max_distance=500):
        """
        Breaks a single MultiPolygon geometry into separate obstacle geometries based on spatial proximity.

        Args:
            geometry: The input geometry (usually a MultiPolygon)
            max_distance: Maximum distance (in map units) to consider geometries as part of the same obstacle cluster

        Returns:
            List of QgsGeometry objects, each representing a distinct obstacle
        """
        if not geometry:
            return []

        log.debug(
            f"Separating avoidance geometry of type {geometry.wkbType()} into distinct obstacles")

        # If it's already a single polygon, return it as a list with one item
        if geometry.wkbType() == WKB_POLYGON:
            return [geometry]

        # For MultiPolygon, extract individual polygons
        individual_geometries = []

        if geometry.wkbType() == WKB_MULTIPOLYGON:
            # Get geometry parts using QGIS API methods
            multi_geom = geometry.constGet()
            for i in range(multi_geom.numGeometries()):
                single_geom = QgsGeometry(multi_geom.geometryN(i).clone())
                if single_geom and not single_geom.isEmpty():
                    individual_geometries.append(single_geom)
        else:
            # If it's not a MultiPolygon but still a valid geometry, treat it as a single obstacle
            individual_geometries = [geometry]

        log.debug(
            f"Extracted {len(individual_geometries)} individual polygons from input geometry")

        # If we only have 0 or 1 geometry, no need for clustering
        if len(individual_geometries) <= 1:
            return individual_geometries

        # Perform spatial clustering based on distance
        clusters = []
        remaining = individual_geometries.copy()

        while remaining:
            # Start a new cluster with the first geometry
            current_cluster = [remaining.pop(0)]
            cluster_changed = True

            # Keep expanding the cluster while we can add geometries to it
            while cluster_changed:
                cluster_changed = False
                current_union = QgsGeometry.unaryUnion(current_cluster)

                # Check each remaining geometry
                i = 0
                while i < len(remaining):
                    # If this geometry is within max_distance of our cluster, add it
                    if current_union.distance(remaining[i]) <= max_distance:
                        current_cluster.append(remaining.pop(i))
                        cluster_changed = True
                    else:
                        i += 1

            # Add the completed cluster to our list and continue with remaining geometries
            if current_cluster:
                clusters.append(QgsGeometry.unaryUnion(current_cluster))

        log.info(
            f"Spatial clustering identified {len(clusters)} distinct obstacle groups")
        return clusters



    def _calculate_geom_heading(self, geom):
        """
        Calculates heading (0-360, CW from N) for a straight line geometry.
        Args:
            geom (QgsGeometry): Line geometry to calculate heading for
        Returns:
            float or None: Heading in degrees (0=North, CW) or None on error
        """
        if not geom or geom.isEmpty():
            log.warning("Invalid geometry for heading calc.")
            return None
        try:
            if geom.type() != WKB_LINE_GEOMETRY:
                # Convert point pair to line if needed
                if geom.type() == WKB_POINT_GEOMETRY:
                    log.warning("Cannot calculate heading from single point.")
                    return None
            # Extract start and end points
            vertices = list(geom.vertices())
            if len(vertices) < 2:
                log.warning("Need at least 2 vertices for heading.")
                return None
            start_pt = vertices[0]
            end_pt = vertices[-1]
            # Calculate heading
            dx = end_pt.x() - start_pt.x()
            dy = end_pt.y() - start_pt.y()
            if abs(dx) < GEOMETRY_PRECISION and abs(dy) < GEOMETRY_PRECISION:
                log.warning("Start and end points are too close.")
                return None
            rad = math.atan2(dx, dy)  # atan2 handles division by zero
            heading = (math.degrees(rad) + 360) % 360
            return heading
        except Exception as e:
            log.error(f"Error calc geom heading: {e}")
            return None

    # --- 5. Straight Lines & Run-ins Generator ---



    def _calculate_and_apply_deviations_v2(self, lines_layer, nogo_layer, clearance_m, turn_radius_m, debug_mode=False):
        """
        Core logic for calculating and applying deviations using the Peak/Tangent approach.

        Args:
            lines_layer (QgsVectorLayer): Layer containing the survey lines
            nogo_layer (QgsVectorLayer): Layer containing the NoGo zones
            clearance_m (float): Clearance distance in meters
            turn_radius_m (float): Minimum turning radius for the vessel in meters
            debug_mode (bool): If True, enables extensive debugging logs

        Returns:
            bool: True if calculation was successful, False otherwise
        """
        QgsProject.instance()

        # Store calculation results for visualization
        self.all_reference_lines = {}
        self.all_peaks = {}

        # Initialize progress variable at the beginning to avoid UnboundLocalError

        # --- Phase 1: Preparation ---
        pass

        # Start editing the lines layer if not already in editing mode
        edit_started_here = False
        if not lines_layer.isEditable():
            if not lines_layer.startEditing():
                return False
            edit_started_here = True
            log.debug(f"Started editing layer: {lines_layer.name()}")

        try:
            # --- PREPARE FIELDS ---
            # Get full field details for better error diagnosis
            if debug_mode:
                field_names = [field.name() for field in lines_layer.fields()]
                log.debug(
                    f"Available fields in layer: {', '.join(field_names)}")

            log.debug("Initializing deviation fields...")
            fld_conflicted_idx = lines_layer.dataProvider().fieldNameIndex("is_conflicted")
            fld_created_idx = lines_layer.dataProvider().fieldNameIndex("is_deviation_created")
            fld_merged_idx = lines_layer.dataProvider().fieldNameIndex("is_line_merged")
            fld_length_idx = lines_layer.dataProvider().fieldNameIndex("Length_m")

            # Detailed logging of field indices
            if debug_mode:
                log.debug(f"Field indices: is_conflicted={fld_conflicted_idx}, " +  # noqa: W504
                          f"is_deviation_created={fld_created_idx}, " +  # noqa: W504
                          f"is_line_merged={fld_merged_idx}, " +  # noqa: W504
                          f"Length_m={fld_length_idx}")

            # Double-check that fields are present
            if -1 in [fld_conflicted_idx, fld_created_idx, fld_merged_idx, fld_length_idx]:
                still_missing = [name for name, idx in zip(
                    ["is_conflicted", "is_deviation_created",
                        "is_line_merged", "Length_m"],
                    [fld_conflicted_idx, fld_created_idx,
                        fld_merged_idx, fld_length_idx]
                ) if idx == -1]
                raise ValueError(
                    f"Required fields still missing after adding: {', '.join(still_missing)}")

            # Initialize values for tracking fields
            log.debug("Resetting deviation fields to initial values...")

            features = lines_layer.getFeatures()
            attr_map = {}
            lines_layer.dataProvider()

            for feature in features:
                attrs = {}
                if fld_conflicted_idx >= 0:
                    attrs[fld_conflicted_idx] = False
                if fld_created_idx >= 0:
                    attrs[fld_created_idx] = False
                if fld_merged_idx >= 0:
                    attrs[fld_merged_idx] = False

                if attrs:
                    attr_map[feature.id()] = attrs

            if attr_map:
                for fid, attrs in attr_map.items():
                    for field_idx, value in attrs.items():
                        self.attribute_changes[fid][field_idx] = value

            log.debug("Deviation fields initialized.")

            # --- PREPARE AVOIDANCE GEOMETRY ---
            log.debug(
                f"Preparing avoidance geometry with clearance {clearance_m}m...")
            avoidance_geom = self._prepare_avoidance_geometry(
                nogo_layer, clearance_m)

            if not avoidance_geom:
                log.error(
                    "Failed to prepare avoidance geometry. Aborting deviation calculation.")
                # Raise exception to trigger rollback
                raise ValueError("Failed to prepare avoidance geometry.")

            if debug_mode:
                log.debug(f"Avoidance geometry type: {avoidance_geom.type()}, " +  # noqa: W504
                          f"Geometry is valid: {avoidance_geom.isGeosValid()}, " +  # noqa: W504
                          f"Is multipart: {avoidance_geom.isMultipart()}")

            # Separate the geometry into distinct components by using spatial clustering
            log.debug("Separating avoidance geometry into distinct obstacles...")
            obstacle_geometries = self._separate_avoidance_geometry(
                avoidance_geom)

            if not obstacle_geometries:
                log.error(
                    "Failed to separate avoidance geometry into obstacles. Aborting.")
                raise ValueError(
                    "Failed to separate avoidance geometry into obstacles.")

            if debug_mode:
                log.debug(
                    f"Identified {len(obstacle_geometries)} distinct obstacle geometries")
                for i, geom in enumerate(obstacle_geometries):
                    log.debug(f"Obstacle {i}: Valid: {geom.isGeosValid()}, " +  # noqa: W504
                              f"Type: {geom.type()}, Area: {geom.area():.2f}")

            # --- IDENTIFY CONFLICTS & GROUP ---
            log.debug("Identifying conflicted lines...")
            # List of (fid, line_geom, line_num, heading)
            conflicted_lines_info = []
            fld_linenum = lines_layer.fields().lookupField("LineNum")
            fld_heading = lines_layer.fields().lookupField("Heading")

            # Use a spatial request to quickly find candidates
            log.debug("Building spatial index for conflict detection...")
            # FIX: Do not use NoGeometry, as the spatial index needs real geometry
            request_geom = QgsFeatureRequest().setSubsetOfAttributes(
                ["LineNum", "Heading"], lines_layer.fields()
            )

            log.debug("Creating spatial index from line features...")
            all_features = {}
            idx = QgsSpatialIndex()
            for feat in lines_layer.getFeatures(request_geom):
                if feat.hasGeometry() and not feat.geometry().isNull():
                    all_features[feat.id()] = feat
                    idx.insertFeature(feat)

            # Use spatial index to quickly find potential conflicts
            log.debug("Using spatial index to find potential conflicts...")
            candidate_ids = idx.intersects(avoidance_geom.boundingBox())
            log.debug(
                f"Found {len(candidate_ids)} potential candidates using spatial index")

            # Detailed intersection check for candidates
            conflicted_fids = {}
            for fid in candidate_ids:
                feat = all_features.get(fid)
                if not feat:
                    continue
                geom = feat.geometry()

                if not geom or geom.isEmpty():
                    continue

                if geom.intersects(avoidance_geom):
                    conflicted_fids[fid] = True

                    # Get LineNum and Heading for this feature if available
                    if fld_linenum >= 0 and fld_heading >= 0:
                        # FIX: Use str() to avoid crashes on duplicates (e.g., "1001_1")
                        line_num_val = feat.attribute(fld_linenum)
                        line_num = str(
                            line_num_val) if line_num_val is not None and line_num_val != NULL else str(fid)
                        heading_val = feat.attribute(fld_heading)

                        heading_float = None
                        if heading_val is not None and heading_val != NULL:
                            try:
                                heading_float = float(heading_val)
                            except (ValueError, TypeError):
                                swallow_exc()

                        if heading_float is None:
                            heading_float = self._calculate_geom_heading(geom)
                            if heading_float is None:
                                heading_float = 0.0

                        conflicted_lines_info.append(
                            (fid, QgsGeometry(geom), line_num, heading_float))
                    else:
                        log.warning(
                            f"Missing LineNum or Heading for FID {fid}. Skipping.")

            if not conflicted_lines_info:
                log.info("No survey lines conflict with the avoidance zones.")
                if edit_started_here:
                    lines_layer.commitChanges()
                return True

            log.info(f"Found {len(conflicted_lines_info)} conflicted lines.")

            # Mark conflicted lines via attribute update
            if conflicted_fids:
                log.debug("Marking conflicted lines in attribute table...")
                for fid in conflicted_fids.keys():
                    self.attribute_changes[fid][fld_conflicted_idx] = True

            # --- GROUPING LOGIC WITH MULTIPLE OBSTACLE SUPPORT ---
            # Group conflicted lines by which obstacle they intersect
            log.debug("Grouping conflicted lines by obstacle...")
            # Dictionary of obstacle_idx -> list of conflicted lines for that obstacle
            obstacle_groups = {}

            # First, sort conflicted lines by LineNum for each group
            conflicted_lines_info.sort(key=lambda item: item[2])

            # Create a mapping of which lines intersect with which obstacles
            if len(obstacle_geometries) > 1:
                log.info(
                    f"Processing {len(obstacle_geometries)} distinct obstacles - grouping lines by obstacle")

                # For each line, check which obstacles it intersects
                for line_idx, (fid, line_geom, line_num, heading) in enumerate(conflicted_lines_info):
                    # Track which obstacles this line intersects
                    line_obstacles = []

                    for obs_idx, obs_geom in enumerate(obstacle_geometries):
                        if line_geom.intersects(obs_geom):
                            if obs_idx not in obstacle_groups:
                                obstacle_groups[obs_idx] = []
                            obstacle_groups[obs_idx].append(
                                (fid, line_geom, line_num, heading, line_idx))
                            line_obstacles.append(obs_idx)

                    log.debug(
                        f"Line {line_num} intersects obstacles: {line_obstacles}")
            else:
                # Just one obstacle - put all lines in the same group
                obstacle_groups[0] = [(fid, line_geom, line_num, heading, idx)
                                      for idx, (fid, line_geom, line_num, heading) in enumerate(conflicted_lines_info)]
                log.info("Single obstacle detected - all lines in same group")

            # Store the results for later visualization
            # This allows the handle_calculate_deviations method to access these
            # for visualization without recomputing
            self.conflicted_lines_info = conflicted_lines_info
            self.obstacle_groups = obstacle_groups
            self.obstacle_centers = {}

            # STEP 1: Calculate the middle line for each obstacle group
            log.debug("Identifying middle reference lines for each obstacle...")
            middle_lines = {}
            for obs_idx, group_lines in obstacle_groups.items():
                if not group_lines:
                    continue

                # Sort by LineNum (should already be sorted, but ensure it)
                group_lines.sort(key=lambda x: x[2])

                # Use median approach to find middle line
                median_idx = len(group_lines) // 2
                middle_fid, middle_geom, middle_num, middle_heading, orig_idx = group_lines[
                    median_idx]

                # Store middle line info for this obstacle
                middle_lines[obs_idx] = {
                    'fid': middle_fid,
                    'geom': middle_geom,
                    'num': middle_num,
                    'heading': middle_heading,
                    'idx': orig_idx
                }

                # Store the obstacle geometry for visualization
                middle_lines[obs_idx]['obstacle_geom'] = obstacle_geometries[obs_idx]

                log.info(
                    f"Obstacle {obs_idx}: Middle reference line identified: {middle_num} at index {orig_idx}")

            # If no obstacles had valid lines, this is an error
            if not middle_lines:
                log.error(
                    "Failed to identify any middle reference lines across all obstacles.")
                raise RuntimeError(
                    "No valid middle reference lines could be identified.")

            # Process each obstacle independently with its own middle reference line
            log.info(
                f"Processing {len(middle_lines)} obstacles with separate reference lines")

            # Store original values for future enhancements and visualization
            for obs_idx, middle_line_info in middle_lines.items():
                middle_line_num = middle_line_info['num']
                middle_line_geom = middle_line_info['geom']
                middle_line_heading = middle_line_info['heading']
                middle_line_info['idx']
                obstacle_geom = middle_line_info.get('obstacle_geom')

                # Store reference information for this obstacle
                self.all_reference_lines[obs_idx] = {
                    'num': middle_line_num,
                    'geom': middle_line_geom,
                    'heading': middle_line_heading,
                    'group_lines': obstacle_groups[obs_idx],
                    'obstacle_geom': obstacle_geom
                }

                # STEP 2: Store the obstacle center (Find Obstacle Center Point)
                if obstacle_geom:
                    self.obstacle_centers[obs_idx] = obstacle_geom.centroid(
                    ).asPoint()

                log.info(
                    f"Obstacle {obs_idx}: Using middle line {middle_line_num} as reference")

            # For centroid calculation (used in various places later)
            avoidance_centroid_geom = avoidance_geom.centroid()
            if not avoidance_centroid_geom or avoidance_centroid_geom.isEmpty():
                log.error("Cannot calculate avoidance zone centroid.")
                # Raise exception for rollback
                raise RuntimeError("Cannot calculate avoidance zone centroid.")
            avoidance_centroid_point = avoidance_centroid_geom.asPoint()  # QgsPoint

            # Log midpoint distances for debugging (kept for backward compatibility)
            log.debug(
                "Calculating midpoint distances to centroid for conflicted lines:")
            for idx, (fid, geom, num, head) in enumerate(conflicted_lines_info):
                midpoint_geom = geom.interpolate(geom.length() / 2.0)
                if not midpoint_geom or not midpoint_geom.isEmpty():
                    midpoint_point = midpoint_geom.asPoint()  # QgsPoint
                    dist_sq = midpoint_point.sqrDist(avoidance_centroid_point)
                    log.debug(
                        f"  Line {num}: Midpoint ({midpoint_point.x():.1f}, {midpoint_point.y():.1f}), DistSq = {dist_sq:.2f}")

            # STEPS 3-4: Calculate Peak Points A and B for each obstacle using perpendicular rays
            for obs_idx, ref_line in self.all_reference_lines.items():
                middle_line_geom = ref_line['geom']
                middle_line_heading = ref_line['heading']

                # Calculate the peaks for this obstacle
                # Use the center of the obstacle instead of midpoint of the line
                obstacle_geom = obstacle_geometries[obs_idx]
                obstacle_centroid = obstacle_geom.centroid()
                mid_pt = obstacle_centroid.asPoint()  # Get the center point of the obstacle
                # Convert to QgsPointXY for distance calculation
                mid_point_xy = QgsPointXY(mid_pt)

                log.debug(
                    f"Using obstacle center at ({mid_pt.x():.1f}, {mid_pt.y():.1f}) for perpendicular rays")
                middle_line_heading_rad = math.radians(middle_line_heading)
                perp_angle_rad_A = middle_line_heading_rad + math.pi / 2.0
                perp_angle_rad_B = middle_line_heading_rad - math.pi / 2.0

                # Use the obstacle boundary to find intersections with perpendicular rays
                try:
                    # For polygon, the boundary would be the exterior ring - we can convert to a line
                    obstacle_boundary = None
                    if obstacle_geom.type() == WKB_POLYGON_GEOMETRY:
                        if obstacle_geom.isMultipart():
                            # For multipolygon, use the part with largest area
                            multi_polygon = obstacle_geom.asMultiPolygon()
                            if multi_polygon:
                                # Find the largest polygon by area
                                largest_idx = 0
                                largest_area = 0
                                for i, polygon in enumerate(multi_polygon):
                                    temp_geom = QgsGeometry.fromPolygonXY(
                                        polygon)
                                    area = temp_geom.area()
                                    if area > largest_area:
                                        largest_area = area
                                        largest_idx = i

                                # Get the exterior ring of the largest polygon
                                if multi_polygon[largest_idx]:
                                    # First ring is exterior
                                    exterior_ring = multi_polygon[largest_idx][0]
                                    obstacle_boundary = QgsGeometry.fromPolylineXY(
                                        exterior_ring)
                        else:
                            # Single polygon
                            polygon = obstacle_geom.asPolygon()
                            # Check if polygon has rings
                            if polygon and polygon[0]:
                                # First ring is exterior
                                exterior_ring = polygon[0]
                                obstacle_boundary = QgsGeometry.fromPolylineXY(
                                    exterior_ring)
                    elif obstacle_geom.type() == WKB_LINE_GEOMETRY:
                        # If it's already a line, use it directly
                        obstacle_boundary = obstacle_geom
                    else:
                        # For other types, just use the original geometry
                        obstacle_boundary = obstacle_geom

                except (ValueError, IndexError, AttributeError) as e:
                    log.warning(f"Could not extract boundary properly: {e}")
                    # Fallback to using the original geometry
                    obstacle_boundary = obstacle_geom

                log.debug(
                    f"Successfully extracted boundary for obstacle {obs_idx}")

                # Create a ray extending from midpoint in perpendicular directions (longer than needed to ensure intersection)
                search_distance = obstacle_geom.boundingBox(
                ).width() + obstacle_geom.boundingBox().height()
                # Use a larger value to ensure we intersect the boundary
                ray_length = max(search_distance, 5000)

                # Ray in direction A
                ray_A_end_x = mid_pt.x() + ray_length * math.sin(perp_angle_rad_A)
                ray_A_end_y = mid_pt.y() + ray_length * math.cos(perp_angle_rad_A)
                ray_A = QgsGeometry.fromPolylineXY(
                    [mid_point_xy, QgsPointXY(ray_A_end_x, ray_A_end_y)])

                # Ray in direction B
                ray_B_end_x = mid_pt.x() + ray_length * math.sin(perp_angle_rad_B)
                ray_B_end_y = mid_pt.y() + ray_length * math.cos(perp_angle_rad_B)
                ray_B = QgsGeometry.fromPolylineXY(
                    [mid_point_xy, QgsPointXY(ray_B_end_x, ray_B_end_y)])

                # Find intersection with obstacle boundary
                intersection_A = ray_A.intersection(obstacle_boundary)
                intersection_B = ray_B.intersection(obstacle_boundary)

                # Use fallback in case of no intersection
                # Reasonable fallback
                offset_dist = max(clearance_m * 1.1, 300.0)
                peak_a_x = mid_pt.x() + offset_dist * math.sin(perp_angle_rad_A)
                peak_a_y = mid_pt.y() + offset_dist * math.cos(perp_angle_rad_A)
                peak_b_x = mid_pt.x() + offset_dist * math.sin(perp_angle_rad_B)
                peak_b_y = mid_pt.y() + offset_dist * math.cos(perp_angle_rad_B)

                # If we found intersection with boundary, use that point instead
                if intersection_A and not intersection_A.isEmpty():
                    # Get the closest intersection point to the midpoint
                    if intersection_A.type() == WKB_POINT_GEOMETRY:
                        if intersection_A.isMultipart():
                            # Multiple intersection points, find closest one
                            points = intersection_A.asMultiPoint()
                            if points:
                                closest_dist = float('inf')
                                closest_point = None
                                for pt in points:
                                    dist = math.sqrt(
                                        (pt.x() - mid_pt.x())**2 + (pt.y() - mid_pt.y())**2)
                                    if dist < closest_dist:
                                        closest_dist = dist
                                        closest_point = pt
                                if closest_point:
                                    peak_a_x = closest_point.x()
                                    peak_a_y = closest_point.y()
                        else:
                            # Single intersection point
                            point = intersection_A.asPoint()
                            peak_a_x = point.x()
                            peak_a_y = point.y()
                    else:
                        # For more complex geometries, try to find the closest point
                        closest_pt = intersection_A.nearestPoint(
                            QgsGeometry.fromPointXY(mid_point_xy))
                        if not closest_pt.isEmpty():
                            peak_a_x = closest_pt.asPoint().x()
                            peak_a_y = closest_pt.asPoint().y()

                if intersection_B and not intersection_B.isEmpty():
                    # Get the closest intersection point to the midpoint
                    if intersection_B.type() == WKB_POINT_GEOMETRY:
                        if intersection_B.isMultipart():
                            # Multiple intersection points, find closest one
                            points = intersection_B.asMultiPoint()
                            if points:
                                closest_dist = float('inf')
                                closest_point = None
                                for pt in points:
                                    dist = math.sqrt(
                                        (pt.x() - mid_pt.x())**2 + (pt.y() - mid_pt.y())**2)
                                    if dist < closest_dist:
                                        closest_dist = dist
                                        closest_point = pt
                                if closest_point:
                                    peak_b_x = closest_point.x()
                                    peak_b_y = closest_point.y()
                        else:
                            # Single intersection point
                            point = intersection_B.asPoint()
                            peak_b_x = point.x()
                            peak_b_y = point.y()
                    else:
                        # For more complex geometries, try to find the closest point
                        closest_pt = intersection_B.nearestPoint(
                            QgsGeometry.fromPointXY(mid_point_xy))
                        if not closest_pt.isEmpty():
                            peak_b_x = closest_pt.asPoint().x()
                            peak_b_y = closest_pt.asPoint().y()

                # Create Peaks for this obstacle
                peak_A = QgsPoint(peak_a_x, peak_a_y)
                peak_B = QgsPoint(peak_b_x, peak_b_y)

                # Store peaks for this obstacle
                self.all_peaks[obs_idx] = {'A': peak_A, 'B': peak_B}

                log.debug(
                    f"Obstacle {obs_idx}: Peak A: {peak_A.x():.1f},{peak_A.y():.1f}, Peak B: {peak_B.x():.1f},{peak_B.y():.1f}")

            # STEPS 5-10: Complete the deviation calculation (handled in _complete_deviation_calculation)
            # This calls the method that implements the remaining steps
            return self._complete_deviation_calculation(lines_layer, obstacle_geometries, clearance_m, turn_radius_m)

        except Exception as e:
            log.exception(f"Error in deviation calculation: {e}")
            if edit_started_here and lines_layer.isEditable():
                lines_layer.rollBack()
                log.info("Changes rolled back due to error")
            return False

    # <<< Helper Function Start: _extract_line_segment (Attempting Explicit LineString access) >>>



    def _complete_deviation_calculation(self, lines_layer, obstacle_geometries, clearance_m, turn_radius_m, debug_mode=False):
        """
        Completes deviation: Creates SMOOTHED connectors, merges segments, finalizes layer updates.
        (Refined V4 + QGIS Native Smoothing + Merging)
        """
        log.info(
            "Completing deviation calculation and finalizing paths (QGIS Smooth + Merging)...")
        QgsProject.instance()

        # --- Layers Setup ---
        deviation_connectors_layer_name = "Deviation_Connectors_Final"
        pass
        deviation_connectors_layer = None  # Initialize
        deviation_provider = None
        # Ensure CRS is valid before creating the layer
        layer_crs = lines_layer.crs()
        if not layer_crs.isValid():
            log.warning(
                "Source layer CRS is invalid. Falling back to project CRS or EPSG:4326 for debug layer.")
            layer_crs = QgsProject.instance().crs()
            if not layer_crs.isValid():
                layer_crs = QgsCoordinateReferenceSystem(
                    "EPSG:4326")  # Last resort

            deviation_connectors_layer = QgsVectorLayer(
                f"LineString?crs={layer_crs.authid()}", deviation_connectors_layer_name, "memory")
            if not deviation_connectors_layer.isValid():
                raise ValueError(
                    f"Failed to create debug connector layer with CRS {layer_crs.authid()}")

            deviation_provider = deviation_connectors_layer.dataProvider()
            provider_fields = [QgsField("LineNum", QVariant.Int), QgsField("OriginalFID", QVariant.Int), QgsField(
                "ObstacleID", QVariant.Int), QgsField("ChosenPeak", QVariant.String), QgsField("Status", QVariant.String)]
            if not deviation_provider.addAttributes(provider_fields):
                raise ValueError(
                    f"Failed to add attributes to debug connector layer: {deviation_provider.lastError()}")
            deviation_connectors_layer.updateFields()
            deviation_connectors_layer.startEditing()
        pass

        # --- Smoothing Parameters ---
        # --- End Smoothing Parameters ---

        # --- Main Processing Block ---
        edit_started_here = False
        lines_layer.dataProvider()
        if not lines_layer.isEditable():
            if not lines_layer.startEditing():
                log.error(
                    f"Failed to start editing on main lines layer: {lines_layer.dataProvider().lastError()}")
                if deviation_connectors_layer and deviation_connectors_layer.isEditable():
                    deviation_connectors_layer.rollBack()
                return False  # Cannot proceed without editing capability
            edit_started_here = True
            log.debug(f"Started editing layer: {lines_layer.name()}")

        try:
            log.info(
                "Processing pre-calculated conflicted lines and path options...")
            results = self._process_conflicted_lines(
                lines_layer, obstacle_geometries, clearance_m, turn_radius_m, debug_mode)
            if not results:
                log.error(
                    "Failed to process conflicted lines. Aborting deviation completion.")
                raise ValueError("Failed to process conflicted lines.")

            log.info(
                f"[COMPLETE] Received results. Path options keys: {list(results.get('path_options', {}).keys())}")
            path_options = results['path_options']
            chosen_paths = results['chosen_paths']
            # List of QgsFeatures
            segments_to_add_outside = results['segments_to_add']
            # List of FIDs
            segments_to_delete_fids = results['segments_to_delete']
            results['process_stats']
            self.path_options = path_options
            self.chosen_paths = chosen_paths
            log.info(
                f"[COMPLETE] Assigned self.path_options ({len(self.path_options)} lines), self.chosen_paths ({len(self.chosen_paths)} lines)")

            # --- Cache Original Attributes ---
            log.debug("Caching attributes of original lines before deletion...")
            original_feature_attributes = {}
            target_fields = lines_layer.fields()
            if segments_to_delete_fids:
                request = QgsFeatureRequest().setFilterFids(segments_to_delete_fids)
                request.setFlags(_QGS_REQUEST_NO_GEOMETRY |  # noqa: W504
                                 _QGS_REQUEST_SUBSET_OF_ATTRIBUTES)
                all_field_names = [target_fields.at(
                    i).name() for i in range(target_fields.count())]
                request.setSubsetOfAttributes(all_field_names, target_fields)

                if target_fields.lookupField("LineNum") == -1:
                    log.warning(
                        "Essential 'LineNum' field missing, ensuring geometry is fetched for attribute caching.")
                    request.setFlags(_QGS_REQUEST_NO_FLAGS)

                for feat in lines_layer.getFeatures(request):
                    attrs = feat.attributes()
                    if not attrs and target_fields.lookupField("LineNum") != -1:
                        log.warning(
                            f"Failed to fetch attributes for FID {feat.id()} despite fields existing? Check request flags.")
                        attrs = [NULL] * len(target_fields)
                    original_feature_attributes[feat.id()] = attrs

                log.debug(
                    f"Cached attributes for {len(original_feature_attributes)} original features.")
            else:
                log.debug("No original lines marked for deletion.")

            # --- Generate Connector Segments (In Memory) ---
            log.info(
                f"Generating connector paths for {len(chosen_paths)} lines (in memory)...")
            segments_to_add_connectors = []
            connectors_added_debug = 0
            fld_lsx_conn = target_fields.lookupField("LowestSP_x")
            fld_lsy_conn = target_fields.lookupField("LowestSP_y")
            fld_hsx_conn = target_fields.lookupField("HighestSP_x")
            fld_hsy_conn = target_fields.lookupField("HighestSP_y")
            coord_indices_valid_conn = all(
                idx != -1 for idx in [fld_lsx_conn, fld_lsy_conn, fld_hsx_conn, fld_hsy_conn])

            for line_num, choices in chosen_paths.items():
                if self.isCanceled(): return False
                for choice in choices:
                    original_fid = choice.get('original_fid')
                    if original_fid in original_feature_attributes:
                        original_attributes = original_feature_attributes[original_fid]
                    else:
                        log.warning(
                            f"No cached attributes for FID {original_fid} (L{line_num}). Using NULLs.")
                        original_attributes = [NULL] * len(target_fields)

                    connector_geom = None
                    smoothing_status = "Not Attempted"

                    try:
                        obs_idx = choice['obstacle_id']
                        peak_label = choice['peak']
                        entry_point = choice['entry_point']
                        peak_point = choice['peak_point']
                        exit_point = choice['exit_point']
                        choice.get('geom_outside1')
                        choice.get('geom_outside2')

                        if not all([entry_point, peak_point, exit_point]):
                            log.warning(
                                f"Skip connector L{line_num}, Obs{obs_idx}: Missing point data.")
                            continue
                        if not all(isinstance(p, QgsPointXY) for p in [entry_point, peak_point, exit_point]):
                            log.warning(
                                f"Skip connector L{line_num}, Obs{obs_idx}: Invalid point types.")
                            continue

                        log.debug(
                            f"  [Curve Prep] L{line_num} Obs{obs_idx}: Points: Entry({entry_point.x():.1f},{entry_point.y():.1f}), Peak({peak_point.x():.1f},{peak_point.y():.1f}), Exit({exit_point.x():.1f},{exit_point.y():.1f})")

                        # --- Mathematical Cosine S-Curve Generation ---
                        # Generate an ideal S-curve ("Hat") that passes exactly through the maximum distance point
                        # and strictly observes the specified vessel turn radius (turn_radius_m).
                        dx_total = exit_point.x() - entry_point.x()
                        dy_total = exit_point.y() - entry_point.y()
                        L_total = math.hypot(dx_total, dy_total)

                        if L_total > 1e-6:
                            ux = dx_total / L_total
                            uy = dy_total / L_total

                            px = peak_point.x() - entry_point.x()
                            py = peak_point.y() - entry_point.y()
                            cross = ux * py - uy * px

                            nx = -uy if cross > 0 else uy
                            ny = ux if cross > 0 else -ux

                            D_peak = abs(cross)

                            num_points = max(32, int(L_total / 15.0))
                            curve_points = []

                            for pt_idx in range(num_points + 1):
                                t = pt_idx / float(num_points)
                                curr_x = entry_point.x() + t * dx_total
                                curr_y = entry_point.y() + t * dy_total

                                offset = D_peak * 0.5 * \
                                    (1.0 - math.cos(2.0 * math.pi * t))
                                pt_x = curr_x + nx * offset
                                pt_y = curr_y + ny * offset
                                curve_points.append(QgsPointXY(pt_x, pt_y))

                            connector_geom = QgsGeometry.fromPolylineXY(
                                curve_points)

                            if connector_geom.isEmpty():
                                connector_geom = QgsGeometry.fromPolylineXY(
                                    [entry_point, peak_point, exit_point])
                                smoothing_status = "Cosine Failed (Empty)"
                            else:
                                smoothing_status = "Cosine S-Curve (Success)"
                                log.info(
                                    f"  [Curve Success] L{line_num}, Obs{obs_idx}: S-Curve generated with {len(curve_points)} points. Peak offset: {D_peak:.1f}m")
                        else:
                            connector_geom = QgsGeometry.fromPolylineXY(
                                [entry_point, peak_point, exit_point])
                            smoothing_status = "Sharp Fallback (Zero Length)"

                        if connector_geom and not connector_geom.isEmpty():
                            connector_heading = None
                            try:
                                if len(list(connector_geom.vertices())) >= 2:
                                    connector_heading = self._calculate_segment_heading(
                                        connector_geom, start=True)
                            except Exception:
                                swallow_exc()

                            connector_feat_mem = QgsFeature(target_fields)
                            connector_feat_mem.setGeometry(connector_geom)
                            connector_feat_mem.setAttributes(
                                original_attributes)
                            connector_feat_mem["Length_m"] = connector_geom.length(
                            )
                            connector_feat_mem["is_line_merged"] = True
                            connector_feat_mem["is_deviation_created"] = True
                            connector_feat_mem["Heading"] = connector_heading if connector_heading is not None else NULL
                            fld_seg_type_idx = target_fields.lookupField(
                                "SegmentType")
                            fld_linenum_idx_conn = target_fields.lookupField(
                                "LineNum")
                            if fld_seg_type_idx != -1:
                                connector_feat_mem[fld_seg_type_idx] = "Connector"
                            if fld_linenum_idx_conn != -1:
                                connector_feat_mem[fld_linenum_idx_conn] = line_num

                            if coord_indices_valid_conn:
                                try:
                                    points = connector_geom.asPolyline()
                                    if len(points) >= 2:
                                        start_v_xy = points[0]
                                        end_v_xy = points[-1]
                                        connector_feat_mem.setAttribute(
                                            fld_lsx_conn, start_v_xy.x())
                                        connector_feat_mem.setAttribute(
                                            fld_lsy_conn, start_v_xy.y())
                                        connector_feat_mem.setAttribute(
                                            fld_hsx_conn, end_v_xy.x())
                                        connector_feat_mem.setAttribute(
                                            fld_hsy_conn, end_v_xy.y())
                                except Exception as update_ex:
                                    log.warning(
                                        f"Error updating coords Connector L{line_num}: {update_ex}")

                            segments_to_add_connectors.append(
                                connector_feat_mem)

                            if deviation_provider:
                                debug_connector_feat = QgsFeature(
                                    deviation_connectors_layer.fields())
                                debug_connector_feat.setGeometry(
                                    connector_geom)
                                debug_connector_feat.setAttributes(
                                    [line_num, original_fid, obs_idx, peak_label, smoothing_status])
                                deviation_provider.addFeature(
                                    debug_connector_feat)
                                connectors_added_debug += 1
                        else:
                            log.warning(
                                f"  [Smooth Skip] L{line_num}, Obs{obs_idx}: Final connector geometry invalid or empty. No connector generated.")

                    except Exception as conn_err:
                        log.error(
                            f"Error creating connector L{line_num}, Obs{obs_idx}: {conn_err}")
                        if deviation_provider:
                            debug_connector_feat = QgsFeature(
                                deviation_connectors_layer.fields())
                            debug_connector_feat.setGeometry(QgsGeometry())
                            debug_connector_feat.setAttributes(
                                [line_num, original_fid, obs_idx, peak_label, f"Error: {conn_err}"])
                            deviation_provider.addFeature(debug_connector_feat)

            log.info(
                f"Generated {len(segments_to_add_connectors)} connector features (in memory).")
            if deviation_connectors_layer:
                log.info(
                    f"Generated {connectors_added_debug} connector features for debug layer.")

            # --- Collect All Generated Segments By LineNum ---
            segments_by_line = defaultdict(list)
            all_new_segments = segments_to_add_outside + segments_to_add_connectors

            fld_linenum_idx_collect = target_fields.lookupField("LineNum")
            if fld_linenum_idx_collect == -1:
                log.error(
                    "Cannot collect segments: LineNum field index not found.")
                raise ValueError(
                    "LineNum field missing, cannot proceed with merging.")

            for segment_feat in all_new_segments:
                try:
                    line_num_val = segment_feat.attribute(
                        fld_linenum_idx_collect)
                    if line_num_val is not None and line_num_val != NULL:
                        segments_by_line[str(line_num_val)].append(
                            segment_feat)
                    else:
                        log.warning(
                            "Segment feature lacks valid LineNum attribute, "
                            "cannot group for merging."
                        )
                except Exception as e:
                    log.warning(
                        f"Error getting LineNum for segment grouping: {e}. Skipping segment.")

            # --- Merge Collected Segments ---
            merged_features = self._merge_line_segments(
                segments_by_line,
                target_fields,
                original_feature_attributes,
                turn_radius_m
            )

            merged_line_nums = set()
            for mf in merged_features:
                ln_val = mf.attribute(fld_linenum_idx_collect)
                if ln_val is not None and ln_val != NULL:
                    merged_line_nums.add(str(ln_val))

            # --- Finalize Layer Updates ---
            # 1. Delete original conflicted lines ONLY IF successfully merged
            if segments_to_delete_fids:
                fids_to_actually_delete = []
                for fid in segments_to_delete_fids:
                    if fid in original_feature_attributes:
                        orig_ln = str(
                            original_feature_attributes[fid][fld_linenum_idx_collect])
                        if orig_ln in merged_line_nums:
                            fids_to_actually_delete.append(fid)
                        else:
                            log.warning(
                                f"Merge failed for line {orig_ln}, keeping original geometry.")

                if fids_to_actually_delete:
                    unique_fids_to_delete = list(set(fids_to_actually_delete))
                    log.info(
                        f"Deleting {len(unique_fids_to_delete)} original lines from '{lines_layer.name()}'.")

                    # FIX: Use layer method instead of provider to respect edit buffer
                    self.deleted_fids.update(unique_fids_to_delete)
                    delete_ok = True
                    if not delete_ok:
                        log.error("Failed delete original features.")
                    else:
                        log.debug("Success delete original features.")
                else:
                    log.debug(
                        "No valid merged lines, so no original features deleted.")
            else:
                log.debug("No original conflicted lines to delete.")

            # 2. Add the NEW MERGED features
            if merged_features:
                log.info(
                    f"Adding {len(merged_features)} merged features to '{lines_layer.name()}'.")

                # FIX: Use layer method instead of provider to respect edit buffer
                self.added_features.extend(merged_features)
                success = True
                if not success:
                    log.error("Failed add merged features to layer.")
                    raise RuntimeError("Failed to add merged features.")
                else:
                    log.debug(
                        f"Success add {len(merged_features)} merged features.")
            else:
                log.warning("No merged features were generated to add.")

            # Commit the main lines layer
            if lines_layer.isEditable():  # Check again in case of prior rollback attempts
                if not lines_layer.commitChanges():
                    commit_errors = lines_layer.commitErrors()
                    log.error(
                        f"CRITICAL: Failed commit lines layer changes: {commit_errors}")
                    pass

                    raise RuntimeError(
                        "Failed to commit changes to lines layer.")
                else:
                    log.info("Successfully committed changes to lines layer.")
                    edit_started_here = False  # Mark commit as successful

            # --- Collect dev_features to be added in main thread ---
            for conn_feat in segments_to_add_connectors:
                if not conn_feat.geometry().isEmpty():
                    new_f = QgsFeature()
                    new_f.setGeometry(conn_feat.geometry())
                    ln_val = conn_feat.attribute(fld_linenum_idx_collect)
                    base_ln = str(ln_val).split('_')[0][:4] if ln_val else "Unknown"
                    new_f.setAttributes([base_ln, conn_feat.geometry().length()])
                    self.dev_features.append(new_f)
            
            log.info(f"Collected {len(self.dev_features)} features for deviation layer.")

            # # --- Finalize Debug Layer ---
            # if deviation_connectors_layer and deviation_provider:
            #     if not deviation_connectors_layer.commitChanges():
            #          log.error(f"Failed commit debug connectors: {deviation_connectors_layer.commitErrors()}")
            #     if deviation_connectors_layer.featureCount() > 0:
            #          project.addMapLayer(deviation_connectors_layer)
            #          try:
            #             # Style the debug layer based on Smoothing Status
            #             categories = []
            #             symbols = { # Define symbols for each status
            #                 "Success": QgsLineSymbol.createSimple({'color': '#00DD00', 'width': '0.7'}), # Green
            #                 "Success (Obstacle Check Skipped)": QgsLineSymbol.createSimple({'color': '#90EE90', 'width': '0.7', 'line_style': 'dash'}),
            #                 "Validation Failed": QgsLineSymbol.createSimple({'color': '#FFA500', 'width': '0.7', 'line_style': 'dash'}),
            #                 "Sharp Geom Invalid": QgsLineSymbol.createSimple({'color': '#FF0000', 'width': '0.7', 'line_style': 'dot'}),
            #                 "Densify Failed": QgsLineSymbol.createSimple({'color': '#FF00FF', 'width': '0.7', 'line_style': 'dash'}),
            #                 "Smooth Failed (Empty)": QgsLineSymbol.createSimple({'color': '#FF00FF', 'width': '0.7', 'line_style': 'dot'}),
            #                 "Not Attempted": QgsLineSymbol.createSimple({'color': '#888888', 'width': '0.5'}),
            #                 "Error": QgsLineSymbol.createSimple({'color': '#AA0000', 'width': '1.0', 'line_style': 'dashdot'}), # Dark Red for Errors
            #             }
            #             default_symbol = QgsLineSymbol.createSimple({'color': '#555555', 'width': '0.5', 'line_style': 'dot'}) # Default Grey Dotted

            #             status_values = set()
            #             for f in deviation_connectors_layer.getFeatures():
            #                 status_val = f['Status']
            #                 if status_val and isinstance(status_val, str):
            #                    if status_val.startswith("Error:"): status_values.add("Error") # Group all errors
            #                    else: status_values.add(status_val)
            #                 elif status_val is None or status_val == NULL:
            #                      status_values.add("Unknown/NULL")

            #             # Create categories only for statuses that actually occurred
            #             for status in status_values:
            #                 sym = symbols.get(status, default_symbol) # Use specific symbol or fallback
            #                 cat_value = status if status != "Unknown/NULL" else NULL
            #                 categories.append(QgsRendererCategory(cat_value, sym, status))

            #             # renderer = QgsCategorizedSymbolRenderer("Status", categories)
            #             # deviation_connectors_layer.setRenderer(renderer)
            #             # deviation_connectors_layer.triggerRepaint()

            #          except Exception as style_ex: log.warning(f"Could not style debug connector layer: {style_ex}")
            #     else: log.warning("No deviation connector paths generated for debug layer.")

            # --- Display Path Options Table ---
            if hasattr(self, 'path_options') and self.path_options:
                log.info(
                    f"[DISPLAY] Calling display table. self.path_options keys: {list(self.path_options.keys())}")
                if not hasattr(self, 'chosen_paths'):
                    self.chosen_paths = chosen_paths
                pass
            else:
                log.warning("No path options recorded.")

            return True  # Indicate overall success

        except Exception as e:
            log.exception(
                f"Error during complete deviation calculation (Merging Version): {e}")
            if edit_started_here and lines_layer.isEditable():
                log.info("Rolling back lines layer due to error.")
                lines_layer.rollBack()
            if deviation_connectors_layer and deviation_connectors_layer.isEditable():
                log.info("Rolling back debug connector layer.")
                deviation_connectors_layer.rollBack()
            return False  # Indicate failure
    # <<< Function End: _complete_deviation_calculation >>>

    # <<< Function Start: _merge_line_segments (Use Original Heading) >>>


    def _process_conflicted_lines(self, lines_layer, obstacle_geometries, clearance_m, turn_radius_m, debug_mode=False):
        """
        Process conflicted lines: Correctly identify split points, calculate peaks relative
        to the gap, create TRUNCATED 'Outside' segments, calculate headings at truncation points,
        store data for Dubins turn.
        (Refined V5 + Phase 1 Headings Added)
        """
        log.info(
            "Starting direct processing of conflicted lines (Refined V5 + Phase 1 Headings)...")

        # Setup (Unchanged)
        path_options = {}
        chosen_paths = {}
        segments_to_add_outside = []
        segments_to_delete = []
        process_stats = {'lines_processed': 0, 'obstacles_processed': 0, 'paths_recorded': 0,
                         'segments_created': 0, 'lines_with_options': set(), 'errors': []}
        conflicted_lines = []
        fld_conflicted_idx = lines_layer.dataProvider().fieldNameIndex("is_conflicted")
        log.info(
            "[DIRECT-DEBUG] Querying conflicted lines "
            "(bypassing provider filter to read edit buffer)"
        )
        if fld_conflicted_idx >= 0:
            # FIX: expression filters ignore unsaved edit buffer.
            # Query directly by FID, which we already determined earlier.
            known_fids = [item[0]
                          for item in getattr(self, 'conflicted_lines_info', [])]
            conflicted_request = QgsFeatureRequest()
            if known_fids:
                conflicted_request.setFilterFids(known_fids)

            conflicted_request.setFlags(_QGS_REQUEST_NO_FLAGS)
            for feature in lines_layer.getFeatures(conflicted_request):
                val = feature.attribute(fld_conflicted_idx)
                if val is True or feature.id() in known_fids:
                    fid = feature.id()
                    line_geom = feature.geometry()
                    line_num_attr = feature.attribute("LineNum")
                    line_num = str(
                        line_num_attr) if line_num_attr is not None and line_num_attr != NULL else str(fid)
                    if line_geom.isEmpty() or not line_geom.isGeosValid():
                        log.warning(f"L{line_num}(FID={fid}) invalid geom")
                        continue
                    conflicted_lines.append(
                        (fid, line_num, line_geom, feature))
            log.info(
                f"[DIRECT-DEBUG] Found {len(conflicted_lines)} conflicted lines.")
        else:
            log.error("Required field 'is_conflicted' not found.")
            return {'path_options': {}, 'chosen_paths': {}, 'segments_to_add': [], 'segments_to_delete': [], 'process_stats': process_stats}

        processed_line_fids = set()
        total_lines_processed = 0

        # Get Field Indices (Unchanged, but ensure target_fields is derived from a valid feature)
        if conflicted_lines:
            # Use fields from the first feature
            target_fields = conflicted_lines[0][3].fields()
            fld_lsx = target_fields.lookupField("LowestSP_x")
            fld_lsy = target_fields.lookupField("LowestSP_y")
            fld_hsx = target_fields.lookupField("HighestSP_x")
            fld_hsy = target_fields.lookupField("HighestSP_y")
            coord_indices_valid = all(
                idx != -1 for idx in [fld_lsx, fld_lsy, fld_hsx, fld_hsy])
            if not coord_indices_valid:
                log.error("SP coordinate fields missing. Cannot update coords.")
        else:
            log.warning(
                "No conflicted lines found, cannot determine target fields.")
            coord_indices_valid = False
            target_fields = QgsFields()  # Create empty fields object to avoid errors later

        # <<< Main Loop >>>
        for fid, line_num, line_geom, feature in conflicted_lines:
            if fid in processed_line_fids:
                continue
            total_lines_processed += 1
            log.info(f"Processing line {line_num} (FID={fid})")
            process_stats['lines_processed'] += 1
            if self.isCanceled(): return False

            # Line Setup (Unchanged)
            line_pts_xy = []
            vertices_iter = line_geom.vertices()
            while vertices_iter.hasNext():
                line_pts_xy.append(QgsPointXY(vertices_iter.next()))
            if len(line_pts_xy) < 2:
                log.warning(f"L{line_num}: Insufficient points.")
                continue
            line_start = line_pts_xy[0]
            line_end = line_pts_xy[-1]
            dx_orig = line_end.x() - line_start.x()
            dy_orig = line_end.y() - line_start.y()
            if abs(dx_orig) > 1e-6 or abs(dy_orig) > 1e-6:
                heading_rad_math = math.atan2(
                    dy_orig, dx_orig)  # Math angle (0=E, CCW)
                # QGIS angle (0=N, CW)
                qgis_heading_orig = (
                    90.0 - math.degrees(heading_rad_math) + 360.0) % 360.0
            else:
                # Fallback to attribute table heading
                h_attr = feature.attribute("Heading")
                try:
                    qgis_heading_orig = float(
                        h_attr) if h_attr is not None and h_attr != NULL else 0.0
                except (ValueError, TypeError):
                    qgis_heading_orig = 0.0

            current_outside_segments = [QgsGeometry(line_geom)]
            line_was_split = False

            # <<< Obstacle Loop >>>
            for obs_idx, obstacle_geom in enumerate(obstacle_geometries):
                if self.isCanceled(): return False
                # FIX: obstacle_geom is already expanded by clearance_m in _prepare_avoidance_geometry!
                # FIX: obstacle_geom is ALREADY expanded by clearance_m in _prepare_avoidance_geometry!
                # Remove the double buffer, which gave 200m instead of 100m.
                obstacle_buffer = obstacle_geom
                if not obstacle_buffer or obstacle_buffer.isEmpty() or not obstacle_buffer.isGeosValid():
                    log.warning(
                        f"Invalid obstacle geometry Obs{obs_idx}. Skipping.")
                    continue

                next_iteration_segments = []
                segments_intersecting_this_obstacle = []
                segments_not_intersecting = []

                # Process each current segment against this obstacle
                for segment in current_outside_segments:
                    if segment and not segment.isEmpty() and segment.intersects(obstacle_buffer):
                        segments_intersecting_this_obstacle.append(segment)
                    elif segment and not segment.isEmpty():
                        segments_not_intersecting.append(segment)

                # If no segments intersect this obstacle, carry over non-intersecting ones and continue
                if not segments_intersecting_this_obstacle:
                    next_iteration_segments.extend(segments_not_intersecting)
                    continue

                log.info(
                    f"  Processing Line {line_num}, Interacting Segment(s) vs Obstacle {obs_idx}")
                process_stats['obstacles_processed'] += 1
                # Collect new segments created by interacting with THIS obstacle
                new_outside_parts_for_this_obstacle = []

                for segment_geom in segments_intersecting_this_obstacle:
                    actual_entry_point = None
                    actual_exit_point = None
                    segment_was_split_this_time = False
                    geom_part1_original = None
                    geom_part2_original = None  # Store original split parts

                    this_seg_products = []  # Keep track of products from this segment safely

                    try:
                        # --- STEP 7 (Splitting) ---
                        # Use difference, not a temp polygon, for more robust splitting
                        outside_geom = segment_geom.difference(obstacle_buffer)
                        self._log_debug_geom(
                            "Difference Result", outside_geom, "debug")  # Log result

                        if outside_geom.isEmpty():
                            log.warning(
                                f"Segment L{line_num} entirely within buffer {obs_idx}.")
                        elif outside_geom.wkbType() == WKB_LINESTRING:
                            log.debug(
                                f"Segment L{line_num} partially inside buffer {obs_idx}, one outside part remains.")
                            this_seg_products.append(outside_geom)
                        elif outside_geom.wkbType() == WKB_MULTILINESTRING:
                            parts = []
                            try:
                                parts_geom = outside_geom.asMultiPolyline()
                                if parts_geom:
                                    parts = parts_geom  # Ensure it's not None
                            except Exception as e:
                                log.error(
                                    f"Error converting MultiLineString parts L{line_num}: {e}")

                            log.debug(f"  Split into {len(parts)} parts.")
                            valid_parts_geoms = [QgsGeometry.fromPolylineXY(
                                p) for p in parts if len(p) >= 2]

                            if len(valid_parts_geoms) >= 2:
                                segment_was_split_this_time = True
                                # Sort parts based on distance from the original segment's start point
                                segment_start_pt = QgsPointXY(
                                    segment_geom.vertexAt(0))
                                valid_parts_geoms.sort(key=lambda g: g.distance(
                                    QgsGeometry.fromPointXY(segment_start_pt)))

                                geom_part1_original = valid_parts_geoms[0]
                                geom_part2_original = valid_parts_geoms[-1]
                                points1 = geom_part1_original.asPolyline()
                                points2 = geom_part2_original.asPolyline()
                                actual_entry_point = QgsPointXY(points1[-1])
                                actual_exit_point = QgsPointXY(points2[0])
                                log.debug(
                                    f"  [P1-Split] L{line_num} Obs{obs_idx}: Split points: Entry({actual_entry_point.x():.1f},{actual_entry_point.y():.1f}), Exit({actual_exit_point.x():.1f},{actual_exit_point.y():.1f})")
                            elif len(valid_parts_geoms) == 1:
                                log.debug(
                                    f" Split resulted in 1 valid part L{line_num}, Obs{obs_idx}.")
                                this_seg_products.extend(valid_parts_geoms)
                            else:
                                log.warning(
                                    f" Split resulted < 1 valid parts L{line_num}, Obs{obs_idx}.")
                        else:
                            log.warning(
                                f" Unexpected geom type {outside_geom.wkbType()} after difference L{line_num}, Obs{obs_idx}.")
                            # Keep original if difference fails unexpectedly
                            this_seg_products.append(segment_geom)
                        # --- STEP 7 END ---

                        # Proceed only if the segment was actually split into two parts
                        if segment_was_split_this_time:
                            line_was_split = True  # Mark that the original line geometry was modified

                            # --- GLOBAL PEAK ASSIGNMENT (Strict Boundary Convergence) ---
                            # Use obstacle centroid so ALL parallel lines,
                            # avoiding it, converge strictly at one maximum point (peak).
                            obs_centroid = obstacle_buffer.centroid().asPoint()
                            if obs_centroid.isEmpty():
                                cx, cy = (actual_entry_point.x() + actual_exit_point.x()) / \
                                    2.0, (actual_entry_point.y() +  # noqa: W504
                                          actual_exit_point.y()) / 2.0
                            else:
                                cx, cy = obs_centroid.x(), obs_centroid.y()
                            mid_point_xy = QgsPointXY(cx, cy)

                            dx_gap = actual_exit_point.x() - actual_entry_point.x()
                            dy_gap = actual_exit_point.y() - actual_entry_point.y()
                            gap_len = math.hypot(dx_gap, dy_gap)

                            if gap_len > 1e-8:
                                dx_norm_gap, dy_norm_gap = dx_gap / gap_len, dy_gap / gap_len
                            else:
                                heading_rad_math = math.radians(
                                    qgis_heading_orig)
                                dx_norm_gap, dy_norm_gap = math.sin(
                                    heading_rad_math), math.cos(heading_rad_math)

                            perp_dx1, perp_dy1 = -dy_norm_gap, dx_norm_gap
                            perp_dx2, perp_dy2 = dy_norm_gap, -dx_norm_gap

                            # Extract boundary of obstacle_buffer safely
                            obs_boundary = None
                            try:
                                if obstacle_buffer.type() == WKB_POLYGON_GEOMETRY:
                                    if obstacle_buffer.isMultipart():
                                        polys = obstacle_buffer.asMultiPolygon()
                                        if polys and polys[0]:
                                            obs_boundary = QgsGeometry.fromPolylineXY(
                                                polys[0][0])
                                    else:
                                        poly = obstacle_buffer.asPolygon()
                                        if poly:
                                            obs_boundary = QgsGeometry.fromPolylineXY(
                                                poly[0])
                            except Exception as e:
                                log.debug(
                                    "Obstacle boundary extraction fallback for line %r: %s", line_num, e)
                            if not obs_boundary or obs_boundary.isEmpty():
                                obs_boundary = obstacle_buffer

                            ray_len = max(5000.0, gap_len * 2)
                            ray_a = QgsGeometry.fromPolylineXY(
                                [mid_point_xy, QgsPointXY(cx + perp_dx1 * ray_len, cy + perp_dy1 * ray_len)])
                            ray_b = QgsGeometry.fromPolylineXY(
                                [mid_point_xy, QgsPointXY(cx + perp_dx2 * ray_len, cy + perp_dy2 * ray_len)])

                            def get_closest_intersection(ray):
                                inter = ray.intersection(obs_boundary)
                                if inter and not inter.isEmpty():
                                    if inter.type() == WKB_POINT_GEOMETRY:
                                        if inter.isMultipart():
                                            pts = inter.asMultiPoint()
                                            if pts:
                                                return min(pts, key=lambda p: (p.x() - cx)**2 + (p.y() - cy)**2)
                                        else:
                                            return inter.asPoint()
                                    else:
                                        nearest = inter.nearestPoint(
                                            QgsGeometry.fromPointXY(mid_point_xy))
                                        if not nearest.isEmpty():
                                            return nearest.asPoint()
                                return None

                            pt_a = get_closest_intersection(ray_a)
                            pt_b = get_closest_intersection(ray_b)

                            if pt_a:
                                peak_a_point = QgsPointXY(pt_a)
                            else:
                                peak_a_point = QgsPointXY(
                                    cx + perp_dx1 * clearance_m, cy + perp_dy1 * clearance_m)

                            if pt_b:
                                peak_b_point = QgsPointXY(pt_b)
                            else:
                                peak_b_point = QgsPointXY(
                                    cx + perp_dx2 * clearance_m, cy + perp_dy2 * clearance_m)

                            # --- Path evaluation and choice ---
                            path_a_length = self._calculate_path_length(
                                actual_entry_point, peak_a_point, actual_exit_point)
                            path_b_length = self._calculate_path_length(
                                actual_entry_point, peak_b_point, actual_exit_point)
                            log.debug(
                                f"  Path Lengths (Revised Peaks): A={path_a_length:.1f}, B={path_b_length:.1f}")
                            if line_num not in path_options:
                                path_options[line_num] = []
                            self._record_path_option(
                                path_options, line_num, "A", path_a_length, actual_entry_point, peak_a_point, actual_exit_point, obs_idx)
                            self._record_path_option(
                                path_options, line_num, "B", path_b_length, actual_entry_point, peak_b_point, actual_exit_point, obs_idx)
                            process_stats['paths_recorded'] += 2
                            process_stats['lines_with_options'].add(line_num)
                            if path_a_length <= path_b_length:
                                chosen_peak = peak_a_point
                                peak_label = "A"
                                log.info(
                                    f"  L{line_num}, Obs{obs_idx}: Peak A chosen (Revised).")
                            else:
                                chosen_peak = peak_b_point
                                peak_label = "B"
                                log.info(
                                    f"  L{line_num}, Obs{obs_idx}: Peak B chosen (Revised).")

                            # --- Calculate Far Points and Truncated Segments ---
                            # --- Dynamic Tangent Offset Calculation for S-Curve ---
                            wx = chosen_peak.x() - actual_entry_point.x()
                            wy = chosen_peak.y() - actual_entry_point.y()
                            D_offset = abs(dx_norm_gap * wy - dy_norm_gap * wx)
                            if D_offset < 1.0:
                                D_offset = 1.0

                            L_req = math.pi * \
                                math.sqrt(
                                    (D_offset * turn_radius_m) / 2.0) * 1.05
                            tangent_offset_dist = max(
                                5.0, L_req - (gap_len / 2.0))
                            log.debug(
                                f"  [Cosine Prep] D_offset={D_offset:.1f}m, L_req={L_req:.1f}m, Gap={gap_len:.1f}m -> Tangent Offset: {tangent_offset_dist:.1f}m")

                            far_entry_point = None
                            far_exit_point = None
                            new_truncated_geom1 = None
                            new_truncated_geom2 = None
                            # --- PHASE 1: Calculate Headings ---
                            entry_heading_qgis = None
                            exit_heading_qgis = None
                            # --- END PHASE 1 ---
                            truncation_failed = False

                            # Process first outside part (before the gap)
                            if geom_part1_original:
                                len1 = geom_part1_original.length()
                                # Distance from START of geom_part1
                                target_dist1 = max(
                                    0.0, len1 - tangent_offset_dist)
                                interp_geom1 = geom_part1_original.interpolate(
                                    target_dist1)
                                if interp_geom1 and not interp_geom1.isEmpty():
                                    far_entry_point = QgsPointXY(
                                        interp_geom1.asPoint())
                                    # Truncate geom_part1_original from its start (0) to target_dist1
                                    new_truncated_geom1 = self._extract_line_segment(
                                        geom_part1_original, 0, target_dist1)
                                    if new_truncated_geom1:
                                        log.debug(
                                            f"  [Dubins Prep] Far Entry Point: ({far_entry_point.x():.1f},{far_entry_point.y():.1f}) on Seg1 (Len:{new_truncated_geom1.length():.1f})")
                                        # --- PHASE 1: Calculate Entry Heading ---
                                        entry_heading_qgis = self._calculate_segment_heading(
                                            new_truncated_geom1, start=False)
                                        log.debug(
                                            f"  [Dubins Prep] Calculated Entry Heading: {entry_heading_qgis}")
                                        # --- END PHASE 1 ---
                                    else:
                                        log.warning(
                                            f"  [Dubins Prep] Failed to truncate Seg1 L{line_num}.")
                                        truncation_failed = True
                                else:
                                    log.warning(
                                        f"  [Dubins Prep] Failed interpolate Far Entry L{line_num}.")
                                    truncation_failed = True
                            else:
                                log.warning(
                                    f"  [Dubins Prep] Original Segment 1 missing L{line_num}.")
                                truncation_failed = True

                            # Process second outside part (after the gap)
                            if geom_part2_original and not truncation_failed:
                                len2 = geom_part2_original.length()
                                # Distance from START of geom_part2
                                target_dist2 = min(len2, tangent_offset_dist)
                                interp_geom2 = geom_part2_original.interpolate(
                                    target_dist2)
                                if interp_geom2 and not interp_geom2.isEmpty():
                                    far_exit_point = QgsPointXY(
                                        interp_geom2.asPoint())
                                    # Truncate geom_part2_original from target_dist2 to its end (len2)
                                    new_truncated_geom2 = self._extract_line_segment(
                                        geom_part2_original, target_dist2, len2)
                                    if new_truncated_geom2:
                                        log.debug(
                                            f"  [Dubins Prep] Far Exit Point: ({far_exit_point.x():.1f},{far_exit_point.y():.1f}) on Seg2 (Len:{new_truncated_geom2.length():.1f})")
                                        # --- PHASE 1: Calculate Exit Heading ---
                                        exit_heading_qgis = self._calculate_segment_heading(
                                            new_truncated_geom2, start=True)
                                        log.debug(
                                            f"  [Dubins Prep] Calculated Exit Heading: {exit_heading_qgis}")
                                        # --- END PHASE 1 ---
                                    else:
                                        log.warning(
                                            f"  [Dubins Prep] Failed to truncate Seg2 L{line_num}.")
                                        truncation_failed = True
                                else:
                                    log.warning(
                                        f"  [Dubins Prep] Failed interpolate Far Exit L{line_num}.")
                                    truncation_failed = True
                            else:
                                # Don't set truncation_failed=True here if it already failed on segment 1
                                if not truncation_failed:
                                    log.warning(
                                        f"  [Dubins Prep] Original Segment 2 missing L{line_num}.")
                                    truncation_failed = True

                            # --- Store Data for Connector ---
                            if line_num not in chosen_paths:
                                # Initialize if first interaction for this line
                                chosen_paths[line_num] = []
                            choice_exists_for_obstacle = any(
                                c.get('obstacle_id') == obs_idx for c in chosen_paths[line_num])

                            if not choice_exists_for_obstacle:
                                if not truncation_failed:
                                    log.debug(
                                        f"  Storing choice with FAR points and TRUNCATED geoms L{line_num}, Obs{obs_idx}")
                                    chosen_paths[line_num].append({
                                        'obstacle_id': obs_idx,
                                        'peak': peak_label,
                                        'entry_point': far_entry_point,
                                        'peak_point': chosen_peak,
                                        'exit_point': far_exit_point,
                                        'original_fid': fid,
                                        'geom_outside1': new_truncated_geom1,
                                        'geom_outside2': new_truncated_geom2,
                                        # --- PHASE 1: Store Headings ---
                                        'entry_heading_qgis': entry_heading_qgis,
                                        'exit_heading_qgis': exit_heading_qgis,
                                        # --- END PHASE 1 ---
                                    })
                                    # Add TRUNCATED parts
                                    if new_truncated_geom1:
                                        this_seg_products.append(
                                            new_truncated_geom1)
                                    if new_truncated_geom2:
                                        this_seg_products.append(
                                            new_truncated_geom2)
                                else:
                                    log.warning(
                                        f"  Truncation failed L{line_num}, Obs{obs_idx}. Storing choice with ORIGINAL split points/geoms and NO headings.")
                                    chosen_paths[line_num].append({
                                        'obstacle_id': obs_idx,
                                        'peak': peak_label,
                                        'entry_point': actual_entry_point,  # Use original split points
                                        'peak_point': chosen_peak,
                                        'exit_point': actual_exit_point,  # Use original split points
                                        'original_fid': fid,
                                        'geom_outside1': geom_part1_original,  # Keep original geometries
                                        'geom_outside2': geom_part2_original,
                                        # --- PHASE 1: Store None for Headings ---
                                        'entry_heading_qgis': None,
                                        'exit_heading_qgis': None,
                                        # --- END PHASE 1 ---
                                    })
                                    # Add ORIGINAL parts
                                    if geom_part1_original:
                                        this_seg_products.append(
                                            geom_part1_original)
                                    if geom_part2_original:
                                        this_seg_products.append(
                                            geom_part2_original)
                            else:
                                log.debug(
                                    f"  Choice for L{line_num}, Obs{obs_idx} already exists, skipping storage.")
                                # Fallback if choice exists
                                if geom_part1_original:
                                    this_seg_products.append(
                                        geom_part1_original)
                                if geom_part2_original:
                                    this_seg_products.append(
                                        geom_part2_original)

                        # Add all valid segment products to the main list
                        new_outside_parts_for_this_obstacle.extend(
                            this_seg_products)

                    except Exception as e:
                        log.exception(
                            f"Error processing segment L{line_num}, Obs{obs_idx}: {e}")
                        process_stats['errors'].append(
                            f"L{line_num}, Obs{obs_idx}, Segment: {str(e)}")
                        # Keep original line if an error occurred midway
                        new_outside_parts_for_this_obstacle.append(
                            segment_geom)

                # Update current_outside_segments for the next obstacle check
                # Combine the parts that didn't intersect this obstacle with the new parts created by this obstacle
                current_outside_segments = segments_not_intersecting + \
                    new_outside_parts_for_this_obstacle
            # <<< End Obstacle Loop >>>

            # --- Final Feature Creation & Deletion Marking ---
            if line_was_split:
                # Mark the original FID as processed
                processed_line_fids.add(fid)
                if fid not in segments_to_delete:
                    # Mark original line for deletion
                    segments_to_delete.append(fid)
                log.info(
                    f"Creating {len(current_outside_segments)} final outside features for line {line_num}")
                for final_segment_geom in current_outside_segments:
                    if final_segment_geom and not final_segment_geom.isEmpty() and final_segment_geom.isGeosValid():
                        # Use fields from original feature
                        feat_final_outside = QgsFeature(target_fields)
                        feat_final_outside.setGeometry(final_segment_geom)
                        # Copy attributes from original
                        feat_final_outside.setAttributes(feature.attributes())
                        feat_final_outside["Length_m"] = final_segment_geom.length(
                        )
                        # Mark as part of a modified line
                        feat_final_outside["is_line_merged"] = True
                        # Indicate deviation process applied
                        feat_final_outside["is_deviation_created"] = True
                        # Update coordinates if possible
                        if coord_indices_valid:
                            try:
                                if final_segment_geom.wkbType() == WKB_LINESTRING:
                                    points = final_segment_geom.asPolyline()
                                    if len(points) >= 2:
                                        start_v_xy = points[0]
                                        end_v_xy = points[-1]
                                        feat_final_outside.setAttribute(
                                            fld_lsx, start_v_xy.x())
                                        feat_final_outside.setAttribute(
                                            fld_lsy, start_v_xy.y())
                                        feat_final_outside.setAttribute(
                                            fld_hsx, end_v_xy.x())
                                        feat_final_outside.setAttribute(
                                            fld_hsy, end_v_xy.y())
                                    else:
                                        log.warning(
                                            f"Cannot update coords for outside segment L{line_num}: < 2 points.")
                                else:
                                    log.warning(
                                        f"Cannot update coords for outside segment L{line_num}: Not LineString.")
                            except Exception as update_ex:
                                log.warning(
                                    f"Error updating coords for outside segment L{line_num}: {update_ex}")
                        segments_to_add_outside.append(feat_final_outside)
                        process_stats['segments_created'] += 1
                    else:
                        log.warning(
                            f"Skipping invalid final outside segment L{line_num}")
            else:
                # Line conflicted but didn't require splitting (e.g., fully contained or only touched)
                log.info(
                    f"Line {line_num} conflicted but no splitting occurred.")
                # If it was marked for deletion previously by another obstacle interaction, keep it marked
                # Otherwise, if it wasn't split, ensure it's NOT marked for deletion
                if fid in segments_to_delete and not any(c.get('original_fid') == fid for choices in chosen_paths.values() for c in choices):
                    log.debug(
                        f"Line {line_num} (FID={fid}) was marked for deletion but wasn't split, removing deletion flag.")
                    segments_to_delete.remove(fid)

        # <<< End Main Loop >>>

        # Final log summary & Return (Unchanged)
        log.info(
            f"Processed {process_stats['lines_processed']} lines vs {process_stats['obstacles_processed']} obstacles.")
        log.info(
            f"Recorded options for {len(process_stats['lines_with_options'])} lines.")
        log.info(f"Created {len(segments_to_add_outside)} 'Outside' features.")
        log.info(
            f"Marked {len(segments_to_delete)} original lines for deletion.")
        if process_stats['errors']:
            log.warning(f"Encountered {len(process_stats['errors'])} errors.")
        log.info(
            f"[DIRECT-DEBUG] Processed {total_lines_processed} lines total.")

        return_dict = {'path_options': path_options, 'chosen_paths': chosen_paths, 'segments_to_add':
                       segments_to_add_outside, 'segments_to_delete': segments_to_delete, 'process_stats': process_stats}
        # Assign to self for potential later use/debugging
        self.path_options = path_options
        log.info(
            f"[DIRECT-ASSIGN] Assigned self.path_options. Keys: {list(self.path_options.keys())}")
        log.info(
            f"[RETURN-CHECK] Returning dict. Path options keys: {list(return_dict.get('path_options', {}).keys())}")
        return return_dict

    # <<< Function Start: _complete_deviation_calculation (Merging Version - Final) >>>


    def _calculate_segment_heading(self, segment_geom, start=True):
        """Calculate heading (0-360 CW from N) for a line segment. (Fixed _is_line_type call)"""
        # --- FIX: Call global function ---
        if not segment_geom or segment_geom.isEmpty() or not is_line_type(segment_geom.wkbType()):
            log.warning("_calculate_segment_heading: Invalid geometry")
            return None
        # --- END FIX ---
        try:
            points = segment_geom.asPolyline()
            if len(points) < 2:
                log.warning("_calculate_segment_heading: Not enough points")
                return None
            if start:
                p1 = points[0]
                p2 = points[1]
            else:
                p1 = points[-2]
                p2 = points[-1]
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                log.warning(
                    "_calculate_segment_heading: Start/End points coincident.")
                if start and len(points) > 2:
                    p2 = points[2]
                    dx = p2.x() - p1.x()
                    dy = p2.y() - p1.y()
                elif not start and len(points) > 2:
                    p1 = points[-3]
                    dx = p2.x() - p1.x()
                    dy = p2.y() - p1.y()
                else:
                    return None
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                return None
            angle_rad = math.atan2(dx, dy)
            heading_deg = math.degrees(angle_rad)
            qgis_heading = (90.0 - heading_deg + 360.0) % 360.0
            return qgis_heading
        except Exception as e:
            log.exception(f"Error in _calculate_segment_heading: {e}")
            return None
    # <<< Helper Function End: _calculate_segment_heading >>>

    # <<< Function Start: _process_conflicted_lines (Phase 1 Headings Added) >>>


    def _merge_line_segments(self, segments_by_line, target_fields, original_feature_attributes, turn_radius_m):
        """
        Merges collected line segments (outside, connector) for each line number
        into a single feature, using the original line's heading. Includes manual
        ordering fallback if QgsGeometryUtils.mergeLines is unavailable/fails.

        Args:
            segments_by_line (dict): {line_num: [list_of_QgsFeature_segments]}
            target_fields (QgsFields): Fields definition for the output layer.
            original_feature_attributes (dict): {original_fid: [attributes]}
            turn_radius_m (float): Turn radius for potential re-smoothing params.

        Returns:
            list: A list of new QgsFeature objects, one for each merged line.
        """
        log.info(
            f"Starting merge process for {len(segments_by_line)} lines (Manual Fallback - Use Original Heading)...")
        merged_features = []
        # --- Field Index Lookups ---
        fld_linenum_idx = target_fields.lookupField("LineNum")
        fld_status_idx = target_fields.lookupField("Status")
        fld_length_idx = target_fields.lookupField("Length_m")
        fld_heading_idx = target_fields.lookupField(
            "Heading")  # Index for Heading field
        target_fields.lookupField("LowestSP")
        target_fields.lookupField("HighestSP")
        fld_lsx_idx = target_fields.lookupField("LowestSP_x")
        fld_lsy_idx = target_fields.lookupField("LowestSP_y")
        fld_hsx_idx = target_fields.lookupField("HighestSP_x")
        fld_hsy_idx = target_fields.lookupField("HighestSP_y")
        fld_is_conflicted_idx = target_fields.lookupField("is_conflicted")
        fld_is_dev_created_idx = target_fields.lookupField(
            "is_deviation_created")
        fld_is_merged_idx = target_fields.lookupField("is_line_merged")
        fld_seg_type_idx = target_fields.lookupField("SegmentType")
        # --- End Field Index Lookups ---

        # --- Re-smoothing & Connection Params ---
        densify_factor_merge = 8.0
        smooth_iterations_merge = 8
        smooth_offset_merge = 0.4
        connect_tolerance = 0.1
        # --- End Params ---

        for line_num, segment_features in segments_by_line.items():
            if self.isCanceled(): return False
            log.debug(
                f"  Merging {len(segment_features)} segments for Line {line_num}")
            if not segment_features:
                log.warning(
                    f"  Skipping Line {line_num}: No segments provided.")
                continue

            valid_segment_geometries = []
            valid_segments_with_info = []
            log.debug(
                f"  Filtering {len(segment_features)} input segments for Line {line_num}...")
            for idx, feat in enumerate(segment_features):
                # ... (Filtering logic as in the previous working version - using is_line_type, isValid, etc.) ...
                geom = feat.geometry()
                segment_valid = False
                if geom and not geom.isEmpty():
                    is_line = is_line_type(geom.wkbType())
                    is_valid = geom.isGeosValid()
                    if is_line and is_valid:
                        try:
                            start_pt = QgsPointXY(geom.vertexAt(0))
                            vertices = list(geom.vertices())
                            if len(vertices) > 0:
                                end_pt = QgsPointXY(vertices[-1])
                                if start_pt and end_pt:
                                    valid_segment_geometries.append(geom)
                                    valid_segments_with_info.append(
                                        {'idx': idx, 'geom': geom, 'start_pt': start_pt, 'end_pt': end_pt, 'feature': feat})
                                    segment_valid = True
                                else:
                                    log.warning(
                                        f"    L{line_num} Seg {idx}: Could not get valid start/end points despite being line type.")
                            else:
                                log.warning(
                                    f"    L{line_num} Seg {idx}: Geometry is a line but has no vertices.")
                        except Exception as e:
                            log.warning(
                                f"    L{line_num} Seg {idx}: Error getting points: {e}. Skipping for manual merge.")
                    else:
                        log.warning(
                            f"    L{line_num} Seg {idx}: Skipped - IsLine={is_line}, IsValid={is_valid}")
                else:
                    log.warning(
                        f"    L{line_num} Seg {idx}: Skipped - Geometry is None or Empty.")

                if not segment_valid:
                    geom_type_str = QgsWkbTypes.displayString(
                        geom.wkbType()) if geom else 'None'
                    log.warning(
                        f"  -> Skipped segment {idx} for Line {line_num}. Reason: Invalid/Empty/Non-Line. Type: {geom_type_str}, IsValid: {geom.isGeosValid() if geom else 'N/A'}")

            log.debug(
                f"  Line {line_num}: Found {len(valid_segments_with_info)} valid segments for merging.")
            if len(valid_segments_with_info) < 1:
                log.warning(
                    f"  Skipping Line {line_num}: No valid geometries remain after filtering for manual merge.")
                continue

            merged_geom = None

            # --- Attempt Merge using QGIS Utils (if available) ---
            # ... (Same try/except block for mergeLines using valid_segment_geometries) ...
            try:
                if hasattr(QgsGeometryUtils, 'mergeLines') and len(valid_segment_geometries) > 0:
                    merged_geom = QgsGeometryUtils.mergeLines(
                        valid_segment_geometries)
                    log.debug(f"  Line {line_num}: Attempted mergeLines.")
                    if merged_geom and not merged_geom.isEmpty() and is_line_type(merged_geom.wkbType()):
                        if merged_geom.isMultipart():
                            log.debug(
                                f"  Line {line_num}: mergeLines produced MultiLine. Falling back to manual merge for guaranteed ordering.")
                            merged_geom = None

                        if merged_geom:
                            log.debug(
                                f"  Line {line_num}: mergeLines successful.")
                        else:
                            log.warning(
                                f"  Line {line_num}: Failed to force Single part.")
                    else:
                        wkb_type_str = QgsWkbTypes.displayString(
                            merged_geom.wkbType()) if merged_geom else 'None'
                        log.warning(
                            f"  Line {line_num}: mergeLines failed or produced Invalid (Type: {wkb_type_str}). Falling back to manual merge.")
                        merged_geom = None
                else:
                    log.info(
                        "  QgsGeometryUtils.mergeLines not available or no valid geometries for it. Proceeding with manual merge.")
                    merged_geom = None
            except Exception as merge_util_err:
                log.warning(
                    f"  Error during mergeLines for Line {line_num}: {merge_util_err}. Falling back to manual merge.")
                merged_geom = None

            # --- Manual Merge Fallback (Using valid_segments_with_info) ---
            if merged_geom is None:
                # ... (Manual merge logic - SAME AS PREVIOUS WORKING VERSION) ...
                log.debug(
                    f"  Attempting manual merge for Line {line_num} using {len(valid_segments_with_info)} valid segments...")
                if not valid_segments_with_info:
                    log.error(
                        f"  Cannot manually merge Line {line_num}: No valid segments available for manual merge.")
                    continue

                try:
                    # 1. Find the starting segment
                    original_lsx = None
                    original_lsy = None
                    for fid, attrs in original_feature_attributes.items():
                        try:
                            if fld_linenum_idx != -1 and len(attrs) > fld_linenum_idx and str(attrs[fld_linenum_idx]) == str(line_num):
                                if fld_lsx_idx != -1 and fld_lsy_idx != -1:
                                    original_lsx = attrs[fld_lsx_idx]
                                    original_lsy = attrs[fld_lsy_idx]
                                break
                        except (TypeError, IndexError):
                            swallow_exc()
                            continue

                    if original_lsx is None or original_lsy is None:
                        log.warning(
                            f"  Cannot manually merge Line {line_num}: Missing original LowestSP coordinates in cache.")
                        continue

                    original_start_point = QgsPointXY(
                        original_lsx, original_lsy)
                    start_segment_info = None
                    min_start_dist_sq = float('inf')

                    for seg_info in valid_segments_with_info:
                        dist_sq = original_start_point.sqrDist(
                            seg_info['start_pt'])
                        if dist_sq < min_start_dist_sq:
                            min_start_dist_sq = dist_sq
                            start_segment_info = seg_info

                    if start_segment_info is None or min_start_dist_sq > (connect_tolerance * 5)**2:
                        log.warning(
                            f"  Cannot manually merge Line {line_num}: Could not identify a valid start segment close enough to original start (MinDistSq: {min_start_dist_sq}).")
                        continue

                    # 2. Order segments
                    ordered_segments_info = []
                    remaining_segments_info = valid_segments_with_info[:]
                    current_segment_info = None

                    for i in range(len(remaining_segments_info)):
                        if remaining_segments_info[i]['idx'] == start_segment_info['idx']:
                            current_segment_info = remaining_segments_info.pop(
                                i)
                            break

                    if not current_segment_info:
                        log.error(
                            f"  Internal error: Start segment info not found in valid list for Line {line_num}.")
                        continue

                    ordered_segments_info.append(current_segment_info)
                    final_vertices = list(
                        current_segment_info['geom'].vertices())

                    while remaining_segments_info:
                        found_next = False
                        current_end_pt = QgsPointXY(final_vertices[-1])
                        best_match_idx = -1
                        # Increased connection tolerance (~5 meters)
                        min_connect_dist_sq = (connect_tolerance * 50)**2
                        reverse_next = False

                        for i in range(len(remaining_segments_info)):
                            next_seg_info = remaining_segments_info[i]

                            dist_to_start_sq = current_end_pt.sqrDist(
                                next_seg_info['start_pt'])
                            if dist_to_start_sq < min_connect_dist_sq:
                                min_connect_dist_sq = dist_to_start_sq
                                best_match_idx = i
                                reverse_next = False
                                found_next = True

                            dist_to_end_sq = current_end_pt.sqrDist(
                                next_seg_info['end_pt'])
                            if dist_to_end_sq < min_connect_dist_sq:
                                min_connect_dist_sq = dist_to_end_sq
                                best_match_idx = i
                                reverse_next = True
                                found_next = True

                        if found_next:
                            current_segment_info = remaining_segments_info.pop(
                                best_match_idx)
                            ordered_segments_info.append(current_segment_info)
                            next_vertices = list(
                                current_segment_info['geom'].vertices())
                            if reverse_next:
                                next_vertices.reverse()
                            if len(next_vertices) > 1:
                                final_vertices.extend(next_vertices[1:])
                        else:
                            log.warning(
                                f"  Manual merge stopped for Line {line_num}: Could not find connecting segment after segment {len(ordered_segments_info)} ending at ({current_end_pt.x():.1f}, {current_end_pt.y():.1f}). Segments remaining: {len(remaining_segments_info)}")
                            final_vertices = None
                            break

                    # 3. Create Merged Geometry
                    if final_vertices and len(final_vertices) >= 2:
                        final_vertices_xy = [QgsPointXY(
                            pt) for pt in final_vertices]
                        merged_geom = QgsGeometry.fromPolylineXY(
                            final_vertices_xy)
                        if merged_geom.isEmpty() or not merged_geom.isGeosValid():
                            log.error(
                                f"  Manual merge for Line {line_num} produced invalid geometry.")
                            merged_geom = None
                        else:
                            log.info(
                                f"  Manual merge successful for Line {line_num}.")
                    else:
                        log.error(
                            f"  Manual merge failed for Line {line_num}: Not enough vertices or connection failed.")
                        merged_geom = None

                except Exception as manual_err:
                    log.exception(
                        f"  Exception during manual merge for Line {line_num}: {manual_err}")
                    merged_geom = None
            # --- End Manual Merge Fallback ---

            if merged_geom is None:
                log.error(
                    f"  Failed to create a valid merged geometry for Line {line_num}. Skipping feature creation.")
                continue

            # --- Optional: Re-Smooth ---
            # ... (Re-smoothing logic - SAME AS PREVIOUS VERSION) ...
            final_geom = merged_geom
            try:
                log.debug(
                    f"  Attempting re-smoothing for merged Line {line_num}...")
                densify_dist_merge = max(
                    1.0, turn_radius_m / densify_factor_merge)
                densified_merge = merged_geom.densifyByDistance(
                    densify_dist_merge)
                if not densified_merge.isEmpty():
                    smoothed_merge = densified_merge.smooth(
                        smooth_iterations_merge, smooth_offset_merge)
                    if not smoothed_merge.isEmpty() and smoothed_merge.isGeosValid():
                        orig_start_re = QgsPointXY(merged_geom.vertexAt(0))
                        mg_vertices = list(merged_geom.vertices())
                        orig_end_re = QgsPointXY(
                            mg_vertices[-1]) if mg_vertices else None
                        smooth_start_re = QgsPointXY(
                            smoothed_merge.vertexAt(0))
                        sm_vertices = list(smoothed_merge.vertices())
                        smooth_end_re = QgsPointXY(
                            sm_vertices[-1]) if sm_vertices else None

                        if orig_end_re and smooth_end_re and \
                           orig_start_re.distance(smooth_start_re) < 1.0 and \
                           orig_end_re.distance(smooth_end_re) < 1.0:
                            log.info(
                                f"  Re-smoothing successful for Line {line_num}. Final length: {smoothed_merge.length():.1f}m")
                            final_geom = smoothed_merge
                        else:
                            log.warning(
                                f"  Re-smoothing endpoint shift too large or failed for Line {line_num}. Using un-smoothed merged geometry.")
                    else:
                        log.warning(
                            f"  Re-smoothing failed (empty/invalid) for Line {line_num}. Using un-smoothed merged geometry.")
                else:
                    log.warning(
                        f"  Densification for re-smoothing failed for Line {line_num}. Using un-smoothed merged geometry.")
            except Exception as smooth_err:
                log.warning(
                    f"  Error during re-smoothing for Line {line_num}: {smooth_err}. Using un-smoothed merged geometry.")
            # --- End Re-Smoothing ---

            # --- Create Final Feature ---
            merged_feature = QgsFeature(target_fields)
            merged_feature.setGeometry(final_geom)

            # --- Populate Attributes ---
            original_attrs = None
            for fid, attrs in original_feature_attributes.items():
                try:
                    if fld_linenum_idx != -1 and len(attrs) > fld_linenum_idx and str(attrs[fld_linenum_idx]) == str(line_num):
                        original_attrs = attrs
                        break
                except (TypeError, IndexError):
                    swallow_exc()
                    continue

            if original_attrs is None:
                log.warning(
                    f"  Could not find original attributes for Line {line_num} to copy from. Using defaults.")
                original_attrs = [NULL] * target_fields.count()
                if fld_linenum_idx != -1:
                    original_attrs[fld_linenum_idx] = line_num
                if fld_status_idx != -1:
                    original_attrs[fld_status_idx] = "To Be Acquired"

            attributes = list(original_attrs)
            if fld_length_idx != -1:
                attributes[fld_length_idx] = final_geom.length()
            if fld_is_conflicted_idx != -1:
                attributes[fld_is_conflicted_idx] = True
            if fld_is_dev_created_idx != -1:
                attributes[fld_is_dev_created_idx] = True
            if fld_is_merged_idx != -1:
                attributes[fld_is_merged_idx] = True
            if fld_seg_type_idx != -1:
                attributes[fld_seg_type_idx] = NULL

            # --- Use ORIGINAL Heading ---
            original_heading = NULL
            if original_attrs and fld_heading_idx != -1 and len(original_attrs) > fld_heading_idx:
                original_heading = original_attrs[fld_heading_idx]
                if original_heading is None or original_heading == NULL:
                    log.warning(
                        f"  Original heading for Line {line_num} was NULL in cache.")

            if fld_heading_idx != -1:
                # Assign original heading
                attributes[fld_heading_idx] = original_heading
                log.debug(
                    f"  Assigned original heading {original_heading} to merged Line {line_num}")
            else:
                log.warning(
                    f"  Heading field index invalid, cannot assign original heading to Line {line_num}")
            # --- End Original Heading ---

            # --- Update start/end points based on FINAL geometry ---
            try:
                final_vertices = list(final_geom.vertices())
                if len(final_vertices) >= 2:
                    start_pt = final_vertices[0]
                    end_pt = final_vertices[-1]
                    if fld_lsx_idx != -1:
                        attributes[fld_lsx_idx] = start_pt.x()
                    if fld_lsy_idx != -1:
                        attributes[fld_lsy_idx] = start_pt.y()
                    if fld_hsx_idx != -1:
                        attributes[fld_hsx_idx] = end_pt.x()
                    if fld_hsy_idx != -1:
                        attributes[fld_hsy_idx] = end_pt.y()
                    log.debug(
                        f"  Updated start/end coordinates for merged Line {line_num}")
                else:
                    log.warning(
                        f"  Merged geom for Line {line_num} has < 2 vertices. Cannot update coords.")
                    # Clear coordinate attributes if vertices are insufficient
                    if fld_lsx_idx != -1:
                        attributes[fld_lsx_idx] = NULL
                    if fld_lsy_idx != -1:
                        attributes[fld_lsy_idx] = NULL
                    if fld_hsx_idx != -1:
                        attributes[fld_hsx_idx] = NULL
                    if fld_hsy_idx != -1:
                        attributes[fld_hsy_idx] = NULL
            except Exception as attr_err:
                log.warning(
                    f"  Error updating coordinates for merged Line {line_num}: {attr_err}")
                # Clear coordinate attributes on error
                if fld_lsx_idx != -1:
                    attributes[fld_lsx_idx] = NULL
                if fld_lsy_idx != -1:
                    attributes[fld_lsy_idx] = NULL
                if fld_hsx_idx != -1:
                    attributes[fld_hsx_idx] = NULL
                if fld_hsy_idx != -1:
                    attributes[fld_hsy_idx] = NULL
            # --- End Update start/end points ---

            merged_feature.setAttributes(attributes)
            merged_features.append(merged_feature)
            log.info(f"  Prepared merged feature for Line {line_num}.")

        # --- End Line Loop ---

        log.info(
            f"Finished merging. Generated {len(merged_features)} final merged features.")
        return merged_features
    # <<< Function End: _merge_line_segments >>>

    # Add the helper function if it's not already present or reliable



    def _repair_geometry(self, geometry):
        """
        Attempts to repair an invalid QgsGeometry using makeValid and buffer(0).

        Args:
            geometry (QgsGeometry): The potentially invalid geometry to repair

        Returns:
            QgsGeometry or None: Repaired geometry or None if repair failed
        """
        log.debug("Attempting geometry repair...")

        if not geometry or geometry.isEmpty():
            return None

        # Try makeValid first
        try:
            valid_geom = geometry.makeValid()
            if valid_geom and not valid_geom.isEmpty() and valid_geom.isGeosValid():
                log.debug("Repaired using makeValid().")
                return valid_geom
        except Exception as e_mv:
            log.debug(f"makeValid error: {e_mv}")

        # If that fails, try buffer(0)
        try:
            log.debug("makeValid failed. Trying buffer(0)...")
            valid_geom = geometry.buffer(0, 5)  # 5 segments per quarter circle
            if valid_geom and not valid_geom.isEmpty() and valid_geom.isGeosValid():
                log.debug("Repaired using buffer(0).")
                return valid_geom
        except Exception as e_buf:
            log.debug(f"buffer(0) error: {e_buf}")

        log.warning("Geometry repair failed.")
        return None



    def _log_debug_geom(self, stage, geom, log_level="debug"):
        """Detailed geometry debugging logger with extensive information."""
        if geom is None:
            log_msg = f"[{stage}] GEOMETRY IS NONE"
            if log_level == "debug":
                log.debug(log_msg)
            elif log_level == "info":
                log.info(log_msg)
            elif log_level == "warning":
                log.warning(log_msg)
            elif log_level == "error":
                log.error(log_msg)
            return

        if geom.isEmpty():
            log_msg = f"[{stage}] GEOMETRY IS EMPTY"
        else:
            geom_type = "Unknown"
            if geom.type() == WKB_POINT_GEOMETRY:
                geom_type = "Point"
                if geom.isMultipart():
                    count = len(geom.asMultiPoint())
                    geom_type = f"MultiPoint ({count} points)"
                else:
                    pt = geom.asPoint()
                    geom_type = f"Point ({pt.x():.4f}, {pt.y():.4f})"
            elif geom.type() == WKB_LINE_GEOMETRY:
                geom_type = "Line"
                if geom.isMultipart():
                    count = len(geom.asMultiPolyline())
                    geom_type = f"MultiLine ({count} segments)"
                else:
                    points = geom.asPolyline()
                    geom_type = f"Line ({len(points)} vertices)"
            elif geom.type() == WKB_POLYGON_GEOMETRY:
                geom_type = "Polygon"
                if geom.isMultipart():
                    count = len(geom.asMultiPolygon())
                    geom_type = f"MultiPolygon ({count} polygons)"
                else:
                    rings = geom.asPolygon()
                    if rings:
                        geom_type = f"Polygon ({len(rings)} rings, {len(rings[0])} vertices in outer ring)"

            log_msg = f"[{stage}] TYPE: {geom_type}, VALID: {geom.isGeosValid()}"

        if log_level == "debug":
            log.debug(log_msg)
        elif log_level == "info":
            log.info(log_msg)
        elif log_level == "warning":
            log.warning(log_msg)
        elif log_level == "error":
            log.error(log_msg)

    # def _calculate_segment_heading(self, segment_geom, from_point=None, start=True):
    #     """
    #     Calculate heading (in degrees) for a line segment.

    #     Args:
    #         segment_geom (QgsGeometry): Line segment geometry
    #         from_point (QgsPointXY, optional): Specific point to calculate heading from
    #         start (bool): Whether to calculate from start (True) or end (False) of segment
    #                      Only used if from_point is None

    #     Returns:
    #         float: Heading in degrees (0-360)
    #     """
    #     if segment_geom.isEmpty() or segment_geom.type() != WKB_LINE_GEOMETRY:
    #         return 0

    #     segment_points = segment_geom.asPolyline()
    #     if len(segment_points) < 2:
    #         return 0

    #     # If from_point specified, find closest point and calculate heading from there
    #     if from_point is not None:
    #         # Convert to QgsPointXY if needed
    #         if not isinstance(from_point, QgsPointXY):
    #             from_point = QgsPointXY(from_point)

    #         # Find closest segment
    #         closest_info = self._find_closest_point_on_line(segment_points, from_point)
    #         if not closest_info:
    #             return 0

    #         segment_idx, _, _ = closest_info

    #         # Use this segment for heading calculation
    #         if segment_idx < len(segment_points) - 1:
    #             p1 = segment_points[segment_idx]
    #             p2 = segment_points[segment_idx + 1]
    #         else:
    #             # Use previous segment if at end
    #             p1 = segment_points[segment_idx - 1]
    #             p2 = segment_points[segment_idx]
    #     else:
    #         # Otherwise use start or end of segment
    #         if start:
    #             p1 = segment_points[0]
    #             p2 = segment_points[1]
    #         else:
    #             p1 = segment_points[-2]
    #             p2 = segment_points[-1]

    #     # Calculate heading (in degrees, clockwise from North)
    #     dx = p2.x() - p1.x()
    #     dy = p2.y() - p1.y()

    #     # Use atan2 to avoid division by zero
    #     angle_rad = math.atan2(dx, dy)  # Note: x,y order for consistent bearing

    #     # Convert to degrees and normalize to 0-360
    #     angle_deg = math.degrees(angle_rad)
    #     if angle_deg < 0:
    #         angle_deg += 360

    #     return angle_deg



    def _record_path_option(self, path_options, line_num, peak_label, path_length, entry_point, peak_point, exit_point, obstacle_id):
        """
        Record a path option in the options table for later analysis.
        Corresponds to storing results of Step 9 evaluation.

        Args:
            path_options (dict): Dictionary to store path options.
            line_num (int): Line number.
            peak_label (str): Label for peak (A or B).
            path_length (float): Calculated path length.
            entry_point (QgsPointXY): Entry point (result of Step 5).
            peak_point (QgsPointXY): Peak point (result of Step 4).
            exit_point (QgsPointXY): Exit point (result of Step 5).
            obstacle_id (int): ID of the obstacle.

        Returns:
            None: Updates path_options dictionary in place.
        """
        source = "Direct"  # Source identifier

        log.info(
            f"[RECORD-{source}] Recording path option for Line {line_num}, Peak {peak_label}, Obstacle {obstacle_id}")
        log.info(f"[RECORD-{source}] Type of path_options: {type(path_options)}, contains: {list(path_options.keys()) if isinstance(path_options, dict) else 'NOT A DICT'}")

        # Ensure points are QgsPointXY
        entry_point_xy = QgsPointXY(entry_point) if not isinstance(
            entry_point, QgsPointXY) else entry_point
        peak_point_xy = QgsPointXY(peak_point) if not isinstance(
            peak_point, QgsPointXY) else peak_point
        exit_point_xy = QgsPointXY(exit_point) if not isinstance(
            exit_point, QgsPointXY) else exit_point

        # Initialize entry for this line if it doesn't exist
        if line_num not in path_options:
            path_options[line_num] = []

        # Record this path option
        path_options[line_num].append({
            'peak': peak_label,
            'length': path_length,
            'entry': entry_point_xy,       # Store QgsPointXY
            'peak_point': peak_point_xy,   # Store QgsPointXY
            'exit': exit_point_xy,         # Store QgsPointXY
            'obstacle_id': obstacle_id
        })

    # Helper function needed by _process_conflicted_lines


    def _extract_line_segment(self, line_geom, start_dist, end_dist):
        """
        Extracts a segment of a line geometry between two distances along the line.
        Attempts to use native curveSubstring via explicit LineString access.
        Falls back to manual iteration if needed.

        Args:
            line_geom (QgsGeometry): The input line geometry
            start_dist (float): Start distance along the line
            end_dist (float): End distance along the line

        Returns:
            QgsGeometry: The extracted line segment, or None on error or if segment is invalid.
        """
        if not line_geom or not line_geom.isGeosValid():
            log.warning("_extract_line_segment: Invalid input geometry")
            return None

        # Check if it's a line type BEFORE trying to access specific methods
        if not is_line_type(line_geom.wkbType()):
            log.warning(
                f"_extract_line_segment: Input geometry is not a line type (Type: {line_geom.wkbType()})")
            return None

        line_length = line_geom.length()
        start_dist = max(0.0, min(start_dist, line_length))
        end_dist = max(0.0, min(end_dist, line_length))

        if abs(start_dist - end_dist) < 1e-9:
            log.debug("_extract_line_segment: Zero or negative length requested.")
            return None

        try:
            # --- Attempt 1: Native curveSubstring ---
            # Check if the method exists directly (might work in some contexts/future versions)
            if hasattr(line_geom, 'curveSubstring'):
                segment_geom = line_geom.curveSubstring(start_dist, end_dist)
                if segment_geom and not segment_geom.isEmpty() and is_line_type(segment_geom.wkbType()):
                    # log.debug("Used direct line_geom.curveSubstring")
                    return segment_geom
                else:
                    log.warning(
                        "Direct line_geom.curveSubstring failed or returned invalid geometry.")
            else:
                log.debug(
                    "line_geom object does not directly have curveSubstring method.")

            # --- Attempt 2: Access as LineString ---
            # If it's specifically a LineString, try accessing it directly
            if line_geom.wkbType() == WKB_LINESTRING:
                line_string_part = line_geom.constGet()  # Get pointer to implementation
                if hasattr(line_string_part, 'curveSubstring'):
                    # QgsLineString::curveSubstring returns a new QgsLineString pointer,
                    # we need to wrap it back into a QgsGeometry
                    new_line_part = line_string_part.curveSubstring(
                        start_dist, end_dist)
                    if new_line_part:
                        segment_geom = QgsGeometry(
                            new_line_part)  # Wrap in QgsGeometry
                        if segment_geom and not segment_geom.isEmpty() and is_line_type(segment_geom.wkbType()):
                            # log.debug("Used line_string_part.curveSubstring")
                            return segment_geom
                        else:
                            log.warning(
                                "line_string_part.curveSubstring failed or returned invalid geometry.")
                    else:
                        log.warning(
                            "line_string_part.curveSubstring returned None")
                else:
                    log.debug(
                        "line_string_part does not have curveSubstring method (unexpected for LineString).")

            # --- Fallback: Manual Extraction (If curveSubstring failed) ---
            log.warning(
                "curveSubstring approaches failed. Falling back to manual extraction.")
            return self._extract_line_segment_manual(line_geom, start_dist, end_dist)

        except Exception as e:
            log.exception(
                f"Error in _extract_line_segment (native/explicit attempts): {e}")
            log.warning(
                "Error during native extraction, falling back to manual.")
            # Fallback to manual extraction on any error during native attempt
            return self._extract_line_segment_manual(line_geom, start_dist, end_dist)
    # <<< Helper Function End: _extract_line_segment >>>

    # <<< Helper Function Start: _extract_line_segment_manual (FIXED AttributeError) >>>



    def _calculate_path_length(self, point1, point2, point3):
        """ Calculate the total length of a three-point path. """
        length1 = math.sqrt((point2.x() - point1.x()) **  # noqa: W504
                            2 + (point2.y() - point1.y())**2)
        length2 = math.sqrt((point3.x() - point2.x()) **  # noqa: W504
                            2 + (point3.y() - point2.y())**2)
        return length1 + length2

    # Helper function needed by _process_conflicted_lines


    def _find_closest_point_on_line(self, line_points, target_point):
        """ Find the closest point on a line (list of QgsPointXY) to a target point. """
        if not line_points or len(line_points) < 2:
            return None
        min_dist_sq = float('inf')
        closest_idx = -1
        closest_proj = None

        for i in range(len(line_points) - 1):
            p1 = line_points[i]
            p2 = line_points[i + 1]
            len_sq = p1.sqrDist(p2)
            if len_sq < 1e-12:
                continue  # Avoid division by zero for coincident points

            # Project target point onto the line segment defined by p1, p2
            # Vector v = p2 - p1; Vector w = target - p1
            vx = p2.x() - p1.x()
            vy = p2.y() - p1.y()
            wx = target_point.x() - p1.x()
            wy = target_point.y() - p1.y()

            dot_vw = wx * vx + wy * vy
            t = dot_vw / len_sq  # Parameter along the segment (0=p1, 1=p2)
            # Clamp t to be within the segment [0, 1]
            t = max(0.0, min(1.0, t))

            # Calculate projected point coordinates
            proj_x = p1.x() + t * vx
            proj_y = p1.y() + t * vy
            proj_pt = QgsPointXY(proj_x, proj_y)

            # Calculate distance squared from target to projected point
            dist_sq = target_point.sqrDist(proj_pt)

            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_idx = i
                closest_proj = proj_pt  # This is the projection ON the segment

        if closest_proj is None:
            return None

        return (closest_idx, closest_proj, math.sqrt(min_dist_sq))




    def _extract_line_segment_manual(self, line_geom, start_dist, end_dist):
        """Extracts segment using interpolation and vertex iteration. (Fixed sqrDist Error)"""
        log.debug(
            f"Executing manual segment extraction for {start_dist:.2f}-{end_dist:.2f}")
        # Re-check basic validity
        if not line_geom or not line_geom.isGeosValid() or not is_line_type(line_geom.wkbType()):
            log.warning(
                "_extract_line_segment_manual: Invalid input geometry")
            return None
        line_length = line_geom.length()
        start_dist = max(0.0, min(start_dist, line_length))
        end_dist = max(0.0, min(end_dist, line_length))
        if abs(start_dist - end_dist) < 1e-6:
            return None

        try:
            points_xy = []
            # Add start point
            start_geom_interpolated = line_geom.interpolate(start_dist)
            if not start_geom_interpolated or start_geom_interpolated.isEmpty():
                log.warning(
                    f"_extract_line_segment_manual: Failed to interpolate start point at {start_dist:.2f}")
                return None
            points_xy.append(QgsPointXY(start_geom_interpolated.asPoint()))

            # Add intermediate vertices
            vertices_iter = line_geom.vertices()
            current_dist = 0.0
            first_vertex = line_geom.vertexAt(0)
            if first_vertex is None:
                log.error(
                    "_extract_line_segment_manual: Cannot get first vertex.")
                return None
            last_point = first_vertex  # QgsPoint

            vertex_index = 0
            while vertices_iter.hasNext():
                current_point = vertices_iter.next()  # QgsPoint
                segment_len = last_point.distance(
                    current_point)  # Uses QgsPoint.distance()

                segment_end_dist = current_dist + segment_len

                # Add vertex if it falls strictly between start and end distances
                if segment_end_dist > start_dist + 1e-6 and segment_end_dist < end_dist - 1e-6:
                    points_xy.append(QgsPointXY(current_point))

                current_dist = segment_end_dist
                last_point = current_point
                vertex_index += 1
                if current_dist > end_dist + 1e-6:
                    break

            # Add end point
            end_geom_interpolated = line_geom.interpolate(end_dist)
            if not end_geom_interpolated or end_geom_interpolated.isEmpty():
                log.warning(
                    f"_extract_line_segment_manual: Failed to interpolate end point at {end_dist:.2f}")
                last_v = line_geom.vertexAt(-1)
                if last_v:
                    points_xy.append(QgsPointXY(last_v))
                    log.debug(
                        "_extract_line_segment_manual: Used last vertex as fallback.")
                else:
                    return None
            else:
                points_xy.append(QgsPointXY(end_geom_interpolated.asPoint()))

            # Remove duplicates
            final_points = []
            if points_xy:
                final_points.append(points_xy[0])
                for i in range(1, len(points_xy)):
                    if points_xy[i].compare(final_points[-1], 0.001) != 0:
                        final_points.append(points_xy[i])

            if len(final_points) >= 2:
                log.debug(
                    f"_extract_line_segment_manual: Extracted segment with {len(final_points)} points.")
                return QgsGeometry.fromPolylineXY(final_points)
            else:
                log.warning(
                    f"_extract_line_segment_manual: Failed, only {len(final_points)} unique points found.")
                return None
        except Exception as e:
            log.exception(f"Error in _extract_line_segment_manual: {e}")
            return None
    # <<< Helper Function End: _extract_line_segment_manual >>>

    # <<< Helper Function Start: _calculate_segment_heading (FIXED _is_line_type call) >>>


