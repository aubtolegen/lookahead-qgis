from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication
from .resources import *
from .lookahead_dockwidget_impl import LookaheadDockWidgetImpl, shutdown_obn_logging
import os
import shutil

try:
    _QT_RIGHT_DOCK_AREA = Qt.DockWidgetArea.RightDockWidgetArea
except AttributeError:
    _QT_RIGHT_DOCK_AREA = Qt.RightDockWidgetArea


class LookaheadPlanner:

    @staticmethod
    def _clear_python_bytecode_cache(plugin_dir):
        """
        Remove stale __pycache__ trees so QGIS reload uses fresh source.
        Safe no-op on any failure.
        """
        try:
            removed = 0
            for root, dirs, _files in os.walk(plugin_dir):
                for d in list(dirs):
                    if d == "__pycache__":
                        cache_dir = os.path.join(root, d)
                        try:
                            shutil.rmtree(cache_dir, ignore_errors=True)
                            removed += 1
                        except Exception:
                            pass
            print(f"[Lookahead] plugin path: {plugin_dir}")
            if removed:
                print(f"[Lookahead] cleared __pycache__ dirs: {removed}")
        except Exception:
            pass

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        self._clear_python_bytecode_cache(self.plugin_dir)

        # initialize locale
        # QSettings can return None/non-string values depending on profile state.
        locale_raw = QSettings().value('locale/userLocale', 'en')
        locale = str(locale_raw or 'en')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'LookaheadPlanner_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Lookahead')
        # Icon goes on the shared QGIS "Plugins" toolbar (addToolBarIcon), not a separate bar.

        self.pluginIsActive = False
        self.dockwidget = None


    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LookaheadPlanner', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action


    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        # Use file-system icon so GUI always matches metadata icon without
        # requiring resources.py recompilation after icon updates.
        icon_path = os.path.join(self.plugin_dir, 'icon.svg')
        open_label = self.tr("Open Lookahead")
        self.add_action(
            icon_path,
            text=open_label,
            callback=self.run,
            status_tip=open_label,
            parent=self.iface.mainWindow())

    #--------------------------------------------------------------------------

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""

        # disconnects
        self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)

        # remove this statement if dockwidget is to remain
        # for reuse if plugin is reopened
        # Commented next statement since it causes QGIS crashe
        # when closing the docked window:
        # self.dockwidget = None

        self.pluginIsActive = False
        shutdown_obn_logging()


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""

        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Lookahead'),
                action)
            self.iface.removeToolBarIcon(action)

        if self.dockwidget is not None:
            try:
                if hasattr(self.dockwidget, "_save_dock_settings"):
                    self.dockwidget._save_dock_settings()
            except Exception:
                pass
            try:
                self.iface.removeDockWidget(self.dockwidget)
            except Exception:
                pass
            try:
                self.dockwidget.deleteLater()
            except Exception:
                pass
            self.dockwidget = None
            # Let Qt destroy the dock before closing file handlers (helps Windows unlock plugin files).
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
                app.processEvents()

        shutdown_obn_logging()

    #--------------------------------------------------------------------------

    def run(self):
        """Run method that loads and starts the plugin"""

        if not self.pluginIsActive:
            self.pluginIsActive = True

            # dockwidget may not exist if:
            #    first run of plugin
            #    removed on close (see self.onClosePlugin method)
            if self.dockwidget is None:
                # Create the dockwidget (after translation) and keep reference
                self.dockwidget = LookaheadDockWidgetImpl()

            self.dockwidget.iface = self.iface

            # Avoid duplicate connections when plugin is reopened.
            try:
                self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)
            except Exception:
                pass
            self.dockwidget.closingPlugin.connect(self.onClosePlugin)

            # show the dockwidget
            # TODO: fix to allow choice of dock location
            self.iface.addDockWidget(_QT_RIGHT_DOCK_AREA, self.dockwidget)
            self.dockwidget.show()
