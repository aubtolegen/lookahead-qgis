"""In-dock HTML help (English default, Russian via lang://ru link)."""

_HELP_LANG_LINK_STYLE = "color:#2563eb;text-decoration:underline;"

LOOKAHEAD_HELP_HTML_EN = f"""
<body style="font-family:Segoe UI,sans-serif; font-size:10pt; color:#222; background:#ffffff;">
<p style="text-align:right;margin:0 0 10px 0;padding-bottom:6px;border-bottom:1px solid #ddd;">
  <span style="color:#555;">Language:</span>
  <b>English</b> &nbsp;|&nbsp;
  <a href="lang://ru" style="{_HELP_LANG_LINK_STYLE}">Russian</a>
</p>

<h2 style="margin-top:0;">Lookahead — quick guide</h2>

<p><b>Tip:</b> use a <b>projected CRS in metres</b> (e.g. UTM) so run-in lengths, clearance and turn radius match real ground distances.</p>

<h3>Typical workflow</h3>
<ol>
  <li><b>Import SPS</b> — import preplot points into a new or existing layer.</li>
  <li>After import, headings are filled automatically; if you edit shots in the attribute table, click <b>Calculate Headings</b>.</li>
  <li>Pick the <b>SPS layer</b>, set <b>Min &amp; Max Lines</b> and <b>Status</b> if needed, then <b>Refresh List</b> to fill the line list.</li>
  <li>Mark lines to shoot as <b>To Be Acquired</b>. Use <b>Acquired</b> or <b>Pending</b> for other lines.</li>
  <li><b>Generate Lookahead Lines</b> — builds survey geometry, run-in / run-out and related layers.</li>
  <li>Optional: <b>Generate Deviation Lines</b> — RRT-based detours around No-Go zones.</li>
  <li>Set <b>Turn Mode</b>, both speed rows (<b>Low→High</b> and <b>High→Low</b>), and <b>Start Time</b>. Then click <b>Run Simulation</b>.</li>
  <li><b>Finalize Lookahead Plan</b> — edit and finalize the sequence. This requires a successful simulation run.</li>
</ol>

<h3>Buttons (top to bottom)</h3>
<ul>
  <li><b>Import SPS File…</b> — wizard to map columns in the SPS text file.</li>
  <li><b>Import CSV ▼</b> — import Sequence/Line plan from CSV:
    quick mode uses columns 0/1 with 0 header rows;
    parsing mode lets you set file, Sequence column, Line column and header rows.
    Parsing import remembers the last mapping + file path and auto-imports on next click when that file still exists.
    If no CSV file path is saved (or the file is missing), it asks you to choose a CSV file each time.
    This fallback selection is used only for the current import and is not written back to parsing settings.
    Default separator is <b>TAB</b>; comma (<b>,</b>), semicolon (<b>;</b>) and pipe (<b>|</b>) are also supported.
    Imported lines are marked <b>To Be Acquired</b> and queued by CSV sequence.
    CSV Seq values are shown as imported; after status removals, the remaining queue is renumbered contiguously.</li>
  <li><b>Calculate Headings</b> — recompute bearing from point order on the selected layer.</li>
  <li><b>Refresh List</b> — rebuild the line list from <b>Min &amp; Max Lines</b>, Status and the current SPS layer.</li>
  <li><b>Remove Status</b> — clear <b>Status</b> on SPS points for selected list lines.</li>
  <li><b>Reset Sequences</b> — clear the <b>shooting-order queue</b>. List selection and status are unchanged.</li>
  <li><b>Duplicate Line</b> — duplicate a list entry. Useful when one line is split into several SP ranges.</li>
  <li><b>Remove Line</b> — remove a row from the list. SPS points are not deleted.</li>
  <li><b>Acquired / To Be Acquired / Pending</b> — write status to SPS and sync to the generated line layer.
    <b>To Be Acquired</b> has a second action: <b>To Be Acq. to Acquired</b> (bulk-convert visible TBA lines to Acquired).</li>
  <li><b>Generate Lookahead Lines</b> — main geometry build. Applies Run-In/Run-Out, clearance, and No-Go rules.</li>
  <li><b>Generate Deviation Lines</b> — deviations for lines already generated.</li>
  <li><b>Run Simulation</b> — Racetrack or Teardrop timing and optimized path display. Refreshes <b>Optimized_Path</b> styling, including <b>mid-segment labels parallel to each leg</b>.</li>
  <li><b>Finalize Lookahead Plan</b> — sequence editor and finalization.</li>
</ul>

<h3>Line list</h3>
<ul>
  <li>Multi-select: <b>Ctrl</b>+click; range: <b>Shift</b>+click.</li>
  <li><b>Sequence is assigned only by queueing with right-click + Shift:</b> use <b>Shift + Right Click</b> on a row to add or remove it from shooting order. Seq numbers are shown in labels.</li>
  <li><b>Run Simulation</b> uses <b>only</b> lines from this queue. Rows marked <b>To Be Acquired</b> are not included until you add them with <b>Shift + Right Click</b>.</li>
  <li>Double-click a row to open the <b>SP range</b> dialog for that line. This trim is used during generation.</li>
</ul>

<h3>Sequence Editor (Finalize Lookahead Plan)</h3>
<ul>
  <li>Segment timings use the same rules as simulation: <b>shooting</b> speed depends on whether that line is acquired <b>Low→High</b> or <b>High→Low</b>; <b>run-in</b>, <b>run-out</b>, and <b>turn</b> use the matching <b>turn</b> speed for that line (and turns ahead of a line use that line’s direction).</li>
  <li><b>Duration</b> shows production (shooting) time only for that line.</li>
  <li><b>Speed (kn)</b> — shooting speed used for that row (from dock settings for <b>Low→High</b> or <b>High→Low</b> according to <b>Direction</b>).</li>
  <li><b>Direction</b> — pass direction per line; <b>Line Change</b> is the next column and shows transition time to the <b>next</b> line: current <b>Run-Out</b> + next <b>Turn</b> + next <b>Run-In</b>.</li>
  <li>The last row has no next line, so <b>Line Change</b> is left empty.</li>
  <li><b>Estimated Line Change Time</b> is the sum of all line-to-line transitions in the sequence.</li>
</ul>

<h3>Individual Turn Editor (Finalize Lookahead Plan)</h3>
<ul>
  <li>Select a turn segment on the preview map to edit only that leg.</li>
  <li>Use <b>Radius (m)</b> and <b>Shape</b> (<b>Racetrack</b>/<b>Teardrop</b>) for the selected turn.</li>
  <li><b>Flip Left/Right</b> switches Dubins branch for that turn.</li>
  <li><b>Undo</b> rolls back the last turn edit.</li>
</ul>

<h3>Acquisition Calendar (Finalize Lookahead Plan)</h3>
<ul>
  <li><b>Timeline</b> — drag the slider to preview vessel position along the optimized path over time (start time is the simulation start).</li>
  <li><b>Vessel</b> label shows the current time at the timeline position; the <b>Marker</b> label shows time at the hovered/clicked point on the path.</li>
  <li><b>Play</b> / <b>Speed</b> — play the timeline; each click on Speed doubles playback (1×, 2×, 4×…).</li>
  <li><b>Real-time 1x</b> — when checked, 1× playback approximates <b>one real second per second</b>; when off, playback uses a faster preview step.</li>
  <li><b>Follow</b> — while <b>Play</b> is running, the map view <b>smoothly pans</b> so the vessel stays in view (higher refresh during playback). The checkbox is <b>disabled while paused</b>. Turning Follow on does not move labels in screen space by itself — labels stay tied to path geometry in map coordinates.</li>
  <li><b>Next Segment</b> — jump the timeline to the start of the next segment in the plan.</li>
  <li><b>Ruler</b> — <b>right-drag</b> on the calendar map for a straight-line measure. Endpoints <b>snap</b> to the path and to segment ends where close enough; distance appears beside the controls in <b>km / m</b> (not mm/cm). <b>Esc</b> clears the ruler when the map widget is focused.</li>
  <li><b>Layers</b> — toggle which project layers are visible in the calendar map (selection is remembered).</li>
  <li><b>Full Extent</b> — zoom to the full extent of the currently enabled layers (default zoom is to <b>Optimized_Path</b>).</li>
  <li>Hover over the path to preview time at that location; click the path to jump the timeline to that time.</li>
  <li><b>Segment labels</b> on the calendar map: <b>Optimized_Path</b> is drawn from an in-memory copy for this dialog only; numbering and duration labels match the main map. Each label is placed at the <b>mid-length</b> of its segment, <b>parallel to the line</b> (same rule as after <b>Run Simulation</b> on the project layer).</li>
  <li>On this tab, the bottom button becomes <b>Close</b> (no Submit/Cancel needed).</li>
</ul>

<h3>Fields &amp; spin boxes</h3>
<ul>
  <li><b>Sail Lines Layer (*.gpkg)</b> — point layer with SPS shots (often created by Import SPS as GeoPackage; any compatible point layer works).</li>
  <li><b>Min &amp; Max Lines</b> — filter by <b>LineNum</b> for the list and processing.</li>
  <li><b>Status</b> — list filter: All (default) / To Be Acquired / Pending / Acquired.</li>
  <li><b>No-Go Zone Layer</b> — polygon layer for avoidance / deviation.</li>
  <li><b>Deviation Clearance</b> (m) — stand-off from No-Go for RRT; negative values are allowed within plugin rules (linked to 2πR). Default 80 m.</li>
  <li><b>Turn Mode</b> — <b>Racetrack (Default)</b> (interleaved pattern) or <b>Teardrop</b> (loop-style turn); affects simulation and turn geometry.</li>
  <li><b>Run-In &amp; Run-Out (m)</b> — max approach and tail lengths; zero run-out can hide that segment. Default run-in 500 m.</li>
  <li><b>Turn Radius</b> (m) and <b>Rate of Turn</b> (deg) — Dubins radius and turn-rate limit.</li>
  <li><b>First Line &amp; First Seq</b> — first line in simulation logic and starting sequence number (shown as Seq in the list).</li>
  <li><b>First Line Heading</b> — first pass direction: Low→High SP or High→Low (reciprocal).</li>
  <li><b>Speeds</b> (knots) — <b>two rows</b> in the dock:
    <ul style="margin-top:4px;">
      <li><b>Low→High</b> — left: shooting along the line for a normal pass; right: turn speed for that pass (run-in/run-out on this line, same direction).</li>
      <li><b>High→Low</b> — same layout for the reciprocal pass (High→Low along the sail line).</li>
      <li><b>Shooting</b> is used for the main <b>Line</b> segment duration (length ÷ speed) for the direction of that line in the sequence.</li>
      <li><b>Turn</b> is used for <b>Run-In</b> and <b>Run-Out</b> lengths at the speed for the line they belong to, and for <b>connector turns</b> between lines using the <b>next</b> line’s pass direction.</li>
      <li>If High→Low was never saved (older settings), it starts equal to Low→High until you change it.</li>
    </ul>
  </li>
  <li><b>Start Time</b> — simulation start date/time for the timeline.</li>
</ul>

<h3>Stability (Advanced)</h3>
<p>Collapsed group at the bottom of the dock. These four values do <b>not</b> change deviation clearance, Dubins geometry, or Racetrack logic — they only tune (1) how strictly run-in polylines are snapped to survey line ends when preparing simulation data, and (2) when the plugin writes a <b>warning to the log</b> that a Teardrop path looks unusually long. Work in a <b>projected CRS in metres</b> so distances are meaningful. Defaults suit most projects.</p>

<h4 style="margin-bottom:4px;">Run-In Endpoint Tol. (m)</h4>
<p>During <b>Run Simulation</b>, the plugin tries to attach each run-in feature to the correct <b>start</b> or <b>end</b> of the survey line (from the run-in layer’s <b>Position</b> attribute). It measures the map distance from the run-in vertex that should lie on the line to the actual line endpoint. If that distance is <b>larger than this tolerance</b>, the run-in is not accepted for that line (you may see “not close to line … point” in the log or lines excluded for missing run-in). <b>Raise</b> the value a few metres if your run-ins visually meet the line but fail due to small coordinate mismatch or CRS/rounding. <b>Lower</b> it only if you need very strict attachment; too low causes false rejections.</p>

<h4 style="margin-bottom:4px;">Teardrop Loop / Chord (factor)</h4>
<p><b>Teardrop mode only.</b> After the teardrop path is built, the plugin compares <b>path length</b> to the <b>straight chord</b> between the turn’s entry and exit points. This check runs only if the chord is longer than <b>Min Chord For Check</b>. Then a warning is logged if <b>either</b>: (A) path length &gt; <b>2π × radius × (Teardrop Loop / 2πR)</b>, <b>or</b> (B) path length &gt; <b>chord × (this factor)</b> <b>and</b> path length &gt; <b>chord + 2 × radius</b>. Larger factor ⇒ harder to trigger the chord-based part of the warning. Smaller factor ⇒ more warnings. This does not change the path — it only affects logging.</p>

<h4 style="margin-bottom:4px;">Teardrop Loop / 2πR (factor)</h4>
<p><b>Teardrop mode only.</b> Compares the teardrop <b>path length</b> to one full circle of radius <b>R</b> (length <b>2πR</b>). If path length &gt; <b>2πR × this factor</b> (and the chord is above <b>Min Chord For Check</b>), a warning is logged that the loop may be excessive — common when line spacing is close to the turn diameter. Default <b>1.05</b> means “more than a full circle by 5%”. Lower values warn sooner; values near <b>1.0</b> are very sensitive.</p>

<h4 style="margin-bottom:4px;">Min Chord For Check (m)</h4>
<p><b>Teardrop mode only.</b> The straight distance between turn entry and exit (the chord) must be <b>greater than this value</b> (map units, metres) before the “excessive teardrop loop” heuristics run at all. Very short chords (tight U-turns on paper) are skipped so you do not get noisy warnings when the geometry is inherently small. If you want warnings even on very short chords, lower this (e.g. toward 0); if you want to silence warnings on short connections, raise it slightly.</p>

<h3>Tips: Racetrack / Teardrop loops and the Turn Editor</h3>
<ul>
  <li>Sometimes the optimized path shows an extra <b>loop</b> or winding in <b>Racetrack</b> or <b>Teardrop</b> mode. That follows <b>deterministic Dubins / teardrop rules</b> plus line spacing, radius and heading constraints — it is <b>not</b> treated as a random software bug. Very long-looking teardrops may trigger optional <b>log hints</b> under <b>Stability (Advanced)</b>; those describe path shape, not a crash.</li>
  <li>In <b>Finalize Lookahead Plan → Turn</b>, if one leg looks tight or awkward, try changing <b>Radius (m) for that turn only</b> by about <b>±1–2 m</b> (or a few metres when line spacing is large). Small nudges often land on a neighbouring feasible path. Combine with <b>Flip Left/Right</b> or <b>Racetrack / Teardrop</b> for that segment if needed.</li>
</ul>

<p style="color:#555;"><i>Click × top-right to close help and return to the panel.</i></p>
</body>
"""

LOOKAHEAD_HELP_HTML_RU = f"""
<body style="font-family:Segoe UI,sans-serif; font-size:10pt; color:#222; background:#ffffff;">
<p style="text-align:right;margin:0 0 10px 0;padding-bottom:6px;border-bottom:1px solid #ddd;">
  <span style="color:#555;">Язык:</span>
  <a href="lang://en" style="{_HELP_LANG_LINK_STYLE}">English</a>
  &nbsp;|&nbsp; <b>Русский</b>
</p>

<h2 style="margin-top:0;">Lookahead — краткая инструкция</h2>

<p><b>Рекомендация:</b> работайте в <b>проекции в метрах</b> (например UTM), чтобы длины run-in, clearance и радиуса совпадали с реальными метрами на карте.</p>

<h3>Типовой порядок</h3>
<ol>
  <li><b>Import SPS</b> — импорт точек преплота в новый или существующий слой.</li>
  <li>После импорта заголовки линий считаются автоматически; при ручном редактировании точек нажмите <b>Calculate Headings</b>.</li>
  <li>Выберите слой SPS, при необходимости <b>Min &amp; Max Lines</b>, <b>Status</b> и нажмите <b>Refresh List</b> — список линий заполнится.</li>
  <li>Отметьте нужные линии статусом <b>To Be Acquired</b>. Для остальных используйте <b>Acquired</b> или <b>Pending</b>.</li>
  <li><b>Generate Lookahead Lines</b> — строит линии съёмки, run-in/run-out и связанные слои.</li>
  <li>При необходимости запустите <b>Generate Deviation Lines</b> — обход No-Go на базе RRT.</li>
  <li>Настройте <b>Turn Mode</b>, обе строки скоростей (<b>Low→High</b> и <b>High→Low</b>) и время старта. Затем нажмите <b>Run Simulation</b>.</li>
  <li><b>Finalize Lookahead Plan</b> — правка последовательности и финализация плана.</li>
</ol>

<h3>Кнопки (сверху вниз)</h3>
<ul>
  <li><b>Import SPS File…</b> — мастер импорта и привязки колонок в тексте SPS.</li>
  <li><b>Import CSV ▼</b> — импорт плана Sequence/Line из CSV:
    быстрый режим берёт колонки 0/1 и 0 строк шапки;
    режим parsing позволяет выбрать файл, колонку Sequence, колонку Line и число строк шапки.
    В parsing запоминаются последние маппинг + путь к файлу; при следующем нажатии импорт стартует сразу, если файл существует.
    Если путь к CSV не сохранён (или файл не найден), каждый раз откроется выбор CSV-файла.
    Такой fallback-выбор используется только для текущего импорта и не записывается обратно в parsing-настройки.
    Разделитель по умолчанию — <b>TAB</b>; также поддерживаются запятая (<b>,</b>), точка с запятой (<b>;</b>) и вертикальная черта (<b>|</b>).
    Импортированные линии помечаются как <b>To Be Acquired</b> и добавляются в очередь по sequence из CSV.
    Seq из CSV показывается как импортирован; после Remove Status оставшаяся очередь перенумеровывается подряд.</li>
  <li><b>Calculate Headings</b> — пересчёт азимута по точкам выбранного слоя. Используйте после правок в таблице.</li>
  <li><b>Refresh List</b> — перестроить список линий по фильтрам Min/Max, Status и выбранному SPS.</li>
  <li><b>Remove Status</b> — сбросить поле Status у выбранных в списке линий.</li>
  <li><b>Reset Sequences</b> — очистить <b>очередь стрельбы</b>. Выделение в списке и статусы не меняются.</li>
  <li><b>Duplicate Line</b> — дубликат выбранной линии. Это удобно, когда одну линию нужно разбить на несколько диапазонов SP.</li>
  <li><b>Remove Line</b> — убрать строку из списка. Точки в SPS не удаляются.</li>
  <li><b>Acquired / To Be Acquired / Pending</b> — записать статус в SPS для выбранных линий и синхронизировать с сгенерированным слоем линий.
    У <b>To Be Acquired</b> есть второе действие: <b>To Be Acq. to Acquired</b> (массовый перевод видимых TBA-линий в Acquired).</li>
  <li><b>Generate Lookahead Lines</b> — основная генерация геометрии. Учитывает Run-In/Run-Out, clearance и No-Go.</li>
  <li><b>Generate Deviation Lines</b> — расчёт отклонений вокруг No-Go для уже сгенерированных линий.</li>
  <li><b>Run Simulation</b> — Racetrack или Teardrop, время, визуализация оптимизованного пути; обновляет стиль <b>Optimized_Path</b>, в том числе <b>подписи в середине сегмента вдоль линии</b>.</li>
  <li><b>Finalize Lookahead Plan</b> — редактор последовательности и финализация. Работает после успешного прогона симуляции.</li>
</ul>

<h3>Список линий</h3>
<ul>
  <li>Обычный мультивыбор: <b>Ctrl</b>+клик; непрерывный диапазон: <b>Shift</b>+клик.</li>
  <li><b>Sequence задаётся только через очередь Shift + правой кнопкой:</b> используйте <b>Shift + правый клик</b> по строке, чтобы добавить или убрать линию из порядка съёмки. Номера Seq видны в подписи строки.</li>
  <li><b>Run Simulation</b> считает <b>только</b> линии из этой очереди. Линии со статусом <b>To Be Acquired</b> сами по себе в расчёт не попадают, пока вы не добавите их через <b>Shift + правый клик</b>.</li>
  <li>Двойной клик по строке открывает диалог диапазона <b>SP</b> для этой линии. Обрезка применяется при генерации.</li>
</ul>

<h3>Sequence Editor (в Finalize Lookahead Plan)</h3>
<ul>
  <li>Расчёт времён совпадает с симуляцией: <b>shooting</b> зависит от того, снята ли линия <b>Low→High</b> или <b>High→Low</b>; <b>run-in</b>, <b>run-out</b> и <b>turn</b> используют соответствующую <b>turn</b>-скорость для этой линии (разворот перед линией — по направлению этой следующей линии).</li>
  <li><b>Duration</b> показывает только производственное время (съёмка) для этой линии.</li>
  <li><b>Speed (kn)</b> — shooting-скорость для этой строки (из настроек дока для <b>Low→High</b> или <b>High→Low</b> в соответствии с колонкой <b>Direction</b>).</li>
  <li><b>Direction</b> — направление прохода; следующая колонка <b>Line Change</b> — время перехода к <b>следующей</b> линии: текущий <b>Run-Out</b> + следующий <b>Turn</b> + следующий <b>Run-In</b>.</li>
  <li>У последней строки нет следующей линии, поэтому <b>Line Change</b> остаётся пустым.</li>
  <li><b>Estimated Line Change Time</b> — сумма всех переходов между линиями в текущей последовательности.</li>
</ul>

<h3>Individual Turn Editor (в Finalize Lookahead Plan)</h3>
<ul>
  <li>Выберите на карте сегмент поворота — редактируется только этот переход.</li>
  <li>Поля <b>Radius (m)</b> и <b>Shape</b> (<b>Racetrack</b>/<b>Teardrop</b>) применяются к выбранному повороту.</li>
  <li><b>Flip Left/Right</b> переключает ветку Дубинса для этого поворота.</li>
  <li><b>Undo</b> отменяет последнее изменение в редакторе поворотов.</li>
</ul>

<h3>Acquisition Calendar (в Finalize Lookahead Plan)</h3>
<ul>
  <li><b>Timeline</b> — двигайте ползунок, чтобы увидеть положение судна на оптимальном пути во времени (старт — время начала симуляции).</li>
  <li>Подпись <b>Vessel</b> показывает текущее время выбранной позиции timeline; <b>Marker</b> показывает время в точке под курсором/по клику на пути.</li>
  <li><b>Play</b> / <b>Speed</b> — проигрывание timeline; кнопка Speed увеличивает скорость в 2 раза (1×, 2×, 4×…).</li>
  <li><b>Real-time 1x</b> — если включено, режим 1× даёт примерно <b>одну реальную секунду на секунду</b> на шкале времени; если выключено — ускоренный предпросмотр.</li>
  <li><b>Follow</b> — во время <b>Play</b> вид карты <b>плавно смещается</b>, чтобы судно оставалось в кадре (повышенная частота обновления на проигрывании). Чекбокс <b>недоступен на паузе</b>. Сам по себе Follow не «приклеивает» подписи к центру экрана — подписи остаются в координатах карты на середине сегмента.</li>
  <li><b>Next Segment</b> — перейти к началу <b>следующего</b> сегмента плана.</li>
  <li><b>Линейка</b> — <b>правый перетаскивающий</b> жест по карте календаря: прямое расстояние между точками. Концы <b>примагничиваются</b> к пути и к концам сегментов при достаточной близости; расстояние показывается у элементов управления в <b>км / м</b> (не мм/см). <b>Esc</b> сбрасывает линейку, когда в фокусе виджет карты.</li>
  <li><b>Layers</b> — включение/выключение видимых слоёв в календаре (выбор запоминается).</li>
  <li><b>Full Extent</b> — зум на охват включенных слоёв (по умолчанию зум на <b>Optimized_Path</b>).</li>
  <li>Наведение на путь показывает время в этой точке; клик по пути переводит timeline в это время.</li>
  <li><b>Подписи сегментов</b> на карте календаря: <b>Optimized_Path</b> рисуется из <b>копии в памяти</b> только для этого окна; номера линий и длительности совпадают с основной картой. Каждая подпись — в <b>середине длины</b> сегмента, <b>вдоль линии</b> (те же правила, что после <b>Run Simulation</b> на проектном слое).</li>
  <li>На этой вкладке нижняя кнопка становится <b>Close</b> (Submit/Cancel не нужны).</li>
</ul>

<h3>Поля и спинбоксы</h3>
<ul>
  <li><b>Sail Lines Layer (*.gpkg)</b> — точечный слой с прострелами SPS (часто после Import SPS как GeoPackage; подойдёт любой совместимый точечный слой).</li>
  <li><b>Min &amp; Max Lines</b> — фильтр по номеру линии (LineNum) для списка и расчётов.</li>
  <li><b>Status</b> — фильтр списка: All (по умолчанию) / To Be Acquired / Pending / Acquired.</li>
  <li><b>No-Go Zone Layer</b> — полигональный слой запретных зон (для отклонений и проверок).</li>
  <li><b>Deviation Clearance</b> (м) — зазор до No-Go при расчёте отклонения; допускаются отрицательные значения в пределах, заданных логикой плагина (связь с 2πR). По умолчанию 80 м.</li>
  <li><b>Turn Mode</b> — <b>Racetrack (Default)</b> (чередование / «кольцо») или <b>Teardrop</b> (петля разворота); влияет на симуляцию и типы поворотов.</li>
  <li><b>Run-In &amp; Run-Out (m)</b> — максимальная длина подхода к линии и выхода; при нулевом run-out соответствующий фрагмент можно скрыть. Run-In по умолчанию 500 м.</li>
  <li><b>Turn Radius</b> (м) и <b>Rate of Turn</b> (deg) — радиус дуг Дубинса и ограничение по скорости поворота судна.</li>
  <li><b>First Line &amp; First Seq</b> — первая линия в логике симуляции и стартовый номер последовательности (отображается в списке как Seq).</li>
  <li><b>First Line Heading</b> — направление первого прохода: Low→High SP или High→Low (reciprocal).</li>
  <li><b>Скорости</b> (knots) — в доке <b>две строки</b>:
    <ul style="margin-top:4px;">
      <li><b>Low→High</b> — слева shooting для обычного прохода вдоль линии; справа turn для этого же направления (run-in/run-out этой линии).</li>
      <li><b>High→Low</b> — то же для обратного (reciprocal) прохода вдоль sail line.</li>
      <li><b>Shooting</b> — длительность основного сегмента <b>Line</b> (длина ÷ скорость) по направлению этой линии в последовательности.</li>
      <li><b>Turn</b> — для <b>Run-In</b> и <b>Run-Out</b> по направлению линии, к которой они относятся; для <b>коннекторного разворота</b> между линиями — по направлению <b>следующей</b> линии.</li>
      <li>Если High→Low ещё не сохраняли (старый конфиг), изначально совпадает с Low→High, пока не отредактируете.</li>
    </ul>
  </li>
  <li><b>Start Time</b> — дата/время начала симуляции (временная шкала сегментов).</li>
</ul>

<h3>Stability (Advanced)</h3>
<p>Свёрнутая группа внизу дока. Эти четыре параметра <b>не</b> меняют clearance отклонений, расчёт Дубинса и режим Racetrack — они настраивают только (1) насколько строго полилинии run-in «прилипают» к концам линий съёмки при подготовке данных для симуляции и (2) когда плагин пишет в <b>лог</b> предупреждение, что путь Teardrop выглядит подозрительно длинным. Задавайте расстояния в <b>метрах проекции</b>. Значения по умолчанию обычно достаточны.</p>

<h4 style="margin-bottom:4px;">Run-In Endpoint Tol. (м)</h4>
<p>При <b>Run Simulation</b> каждый отрезок run-in должен стыковаться с нужным <b>началом</b> или <b>концом</b> линии съёмки (по полю <b>Position</b> в слое run-in). Плагин измеряет расстояние в карте от вершины run-in, которая должна лежать на линии, до фактической конечной точки линии. Если расстояние <b>больше этого допуска</b>, run-in для этой линии не принимается (в логе могут быть сообщения «not close to line … point», линии могут отфильтроваться как без run-in). <b>Увеличьте</b> допуск на несколько метров, если на карте стык выглядит нормально, но из‑за погрешности координат/CRS проверка не проходит. <b>Уменьшайте</b> только если нужна очень жёсткая привязка; слишком мало — ложные отказы.</p>

<h4 style="margin-bottom:4px;">Teardrop Loop / Chord (коэффициент)</h4>
<p><b>Только режим Teardrop.</b> После построения дуги сравнивается <b>длина пути разворота</b> с <b>прямой хордой</b> между точками входа и выхода. Проверка выполняется, только если хорда длиннее <b>Min Chord For Check</b>. Тогда в лог пишется предупреждение, если выполняется <b>хотя бы одно</b>: (A) длина пути &gt; <b>2π × R × (Teardrop Loop / 2πR)</b>, <b>или</b> (B) длина пути &gt; <b>хорда × этот коэффициент</b> <b>и</b> длина пути &gt; <b>хорда + 2R</b>. Больший коэффициент — реже срабатывает «хордовая» часть условия. Меньший — чаще предупреждения. На саму геометрию это не влияет, только на запись в лог.</p>

<h4 style="margin-bottom:4px;">Teardrop Loop / 2πR (коэффициент)</h4>
<p><b>Только Teardrop.</b> Сравнивает длину пути разворота с длиной полного круга радиуса <b>R</b>, то есть <b>2πR</b>. Если длина пути &gt; <b>2πR × этот коэффициент</b> (и хорда больше порога <b>Min Chord For Check</b>), в лог выводится предупреждение о возможно избыточной «петле» — типично, когда межлинейное расстояние близко к диаметру разворота. Значение по умолчанию <b>1.05</b> — «длиннее полного круга более чем на 5%». Ближе к <b>1.0</b> — чувствительнее; выше — реже предупреждения.</p>

<h4 style="margin-bottom:4px;">Min Chord For Check (м)</h4>
<p><b>Только Teardrop.</b> Прямое расстояние между входом и выходом поворота (хорда) должно быть <b>больше этого значения</b> (метры в карте), иначе эвристики «избыточной петли» <b>не запускаются</b> — чтобы не засорять лог на заведомо коротких соединениях. Чтобы предупреждения смотрели и очень короткие хорды — уменьшите параметр (к нулю). Чтобы реже предупреждать на коротких стыках — слегка увеличьте.</p>

<h3>Советы: петли Racetrack/Teardrop и редактор поворота</h3>
<ul>
  <li>Иногда в режимах <b>Racetrack</b> или <b>Teardrop</b> на пути видна <b>дополнительная петля</b> или лишний обход. Это следствие <b>жёсткой геометрии</b> (Дубинс / тип разворота), интервала между линиями, радиуса и ограничений по курсу — <b>не</b> «случайный баг» плагина. Очень длинный teardrop может давать записи в лог из блока <b>Stability (Advanced)</b> — там оценка формы пути, а не сообщение о падении.</li>
  <li>В <b>Finalize Lookahead Plan → вкладка поворота</b>, если конкретный переход выглядит натянутым, попробуйте для <b>этого поворота</b> изменить <b>Radius (m)</b> примерно на <b>±1–2 м</b> (на крупном шаге линий иногда имеет смысл сдвиг на несколько метров) — часто это переключает расчёт на соседнее допустимое решение. Дополнительно используйте <b>Flip Left/Right</b> или смену <b>Racetrack / Teardrop</b> только для выбранного сегмента.</li>
</ul>

<h3>Сообщения</h3>
<p>Короткие уведомления показываются в <b>панели сообщений QGIS</b> и исчезают через несколько секунд; вопросы «Да/Нет» по-прежнему открывают обычное окно.</p>

<p style="color:#555;"><i>Закройте эту справку кнопкой × справа вверху, чтобы вернуться к панели.</i></p>
</body>
"""
