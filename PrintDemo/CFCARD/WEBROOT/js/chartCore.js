// js/chartCore.js — X67 锁标 EChart 引擎（含 DrawingMode 0/1/2/3 与 BST 10/11）

var LockChart = (function () {

  var chart = null;

  var config = {
    mode: 'x67_standard',
    circumference: 690,
    dataPoints: 1000,
    yMin: 0,
    yMax: 255
  };

  var UDINT_MAX = 4294967295; // 无效位置（PLC）
  /** 三色通道合成曲线 Y 轴上界 255+255+255 */
  var BST_COMBINE_Y_MAX = 765;
  var BSTMK_SELF  = 0x01;
  var BSTMK_FRONT = 0x02;
  var BSTMK_FIRST = 0x04;
  /** 与 X67 锁存 markArea 一致；模式10/11 BST 锁标浮动框也以此底色（不另用 udiCurLatch 画灰带/竖线） */
  var BST_LOCK_AREA_FILL = 'rgba(158,158,158,0.30)';
  var BST_TOUCH_MAREA = { color: 'rgba(0,0,0,0)', borderColor: '#1976d2', borderWidth: 2 };

  /** 主图下方 RGB 色带高度 */
  var BST_STRIP_H = 12;
  /** 主图坐标区下沿到色条顶部的距离（留出 x 轴刻度与「mm」单位，避免被色条挡住） */
  var BST_STRIP_TOP_OFFSET = 28;

  var state = {
    touchPosMm: null,
    lockedPosMm: null,
    windowWidthMm: 16,
    drawMode: 0,
    puWindowIntervalMm: 0,
    markSelfMm: null,
    markFirstMm: null,
    markFrontMm: null,
    markEnableBst: 0,
    /** 色带/采样：g1~g3（group1/2/3 字节列），模式10 与模式11 上图共用 */
    bstStripRgb: null,
    /** 仅模式11 下图 + 下图下色带：g4~g6（group4/5/6） */
    bstStripRgbB: null
  };

  var drag = { active: false, lastPosMm: null, pendingEvent: null };
  var _rafId = null;
  var callbacks = { onDrag: null, onDragEnd: null };
  var _appliedLayout = -1;

  // ─── 初始化 ────────────────────────────────────────────

  function init(containerId, userConfig) {
    if (userConfig) {
      for (var k in userConfig) {
        if (userConfig.hasOwnProperty(k)) config[k] = userConfig[k];
      }
    }
    var dom = document.getElementById(containerId);
    if (!dom) { console.error('LockChart: 找不到 #' + containerId); return null; }

    chart = echarts.init(dom);
    applyLayout();

    window.addEventListener('resize', function () {
      if (!chart) return;
      chart.resize();
      if (state.drawMode === 10 || state.drawMode === 11) {
        chart.setOption({ graphic: buildGraphicElements(false) });
      }
    });

    var zr = chart.getZr();
    zr.on('mousedown', onDragStart);
    zr.on('mousemove', onDragMove);
    zr.on('mouseup', onDragEnd);
    zr.on('globalout', onDragEnd);

    chart.on('datazoom', function () {
      chart.setOption({ graphic: buildGraphicElements(false) });
    });

    return chart;
  }

  // ─── 布局构建 ──────────────────────────────────────────

  function xInterval() {
    var c = config.circumference;
    if (c >= 1200) return 100;
    if (c >= 600)  return 50;
    if (c >= 300)  return 20;
    return 10;
  }

  function tooltipFmt(params) {
    if (!params || !params.length) return '';
    var s = params[0].value[0].toFixed(1) + ' mm<br/>';
    for (var i = 0; i < params.length; i++) {
      s += params[i].marker + ' ' + params[i].seriesName +
           ': <b>' + params[i].value[1] + '</b><br/>';
    }
    return s;
  }

  function makeXAxis(gridIdx) {
    var o = {
      type: 'value', min: 0, max: config.circumference,
      name: 'mm', nameLocation: 'end', nameGap: 4,
      nameTextStyle: { fontSize: 10, color: '#999' },
      axisLabel: { fontSize: 10 },
      splitLine: { show: false },
      minorTick: { show: true, splitNumber: 5 },
      interval: xInterval()
    };
    if (gridIdx !== undefined) o.gridIndex = gridIdx;
    return o;
  }

  function makeYAxis(gridIdx, yMax) {
    // 工单1: 隐藏纵坐标（Y 轴轴线/刻度/标签/分割线全部不可见）
    var yTop = (yMax != null && !isNaN(yMax)) ? yMax : config.yMax;
    var o = {
      type: 'value', min: config.yMin, max: yTop,
      show: false,
      splitLine: { show: false }
    };
    if (gridIdx !== undefined) o.gridIndex = gridIdx;
    return o;
  }

  /** 与当前绘制模式一致的主区 Y 轴上界（BST 合成为 765，其余为单通道 255） */
  function displayYMax() {
    if (state.drawMode === 10 || state.drawMode === 11) return BST_COMBINE_Y_MAX;
    return config.yMax;
  }

  function makeZoomInside(xIdxArr) {
    return {
      type: 'inside', xAxisIndex: xIdxArr, filterMode: 'none',
      zoomOnMouseWheel: true, moveOnMouseMove: false, moveOnMouseWheel: false
    };
  }

  function makeZoomSlider(xIdxArr) {
    return {
      type: 'slider', xAxisIndex: xIdxArr, filterMode: 'none',
      height: 18, bottom: 8, borderColor: '#ccc',
      fillerColor: 'rgba(25,118,210,0.12)', handleSize: '60%',
      showDetail: true,
      labelFormatter: function (v) { return v.toFixed(1); }
    };
  }

  function makeSeries(name, color, extra) {
    var s = {
      name: name, type: 'line', symbol: 'none',
      lineStyle: { color: color, width: 1.2 },
      itemStyle: { color: color },
      large: true, largeThreshold: 500,
      data: []
    };
    if (extra) { for (var k in extra) { if (extra.hasOwnProperty(k)) s[k] = extra[k]; } }
    return s;
  }

  function layoutKey() {
    if (state.drawMode === 1) return 1;
    if (state.drawMode === 11) return 2; // BST 双光眼：上/下区均为 RGB 合（g1+2+3 / g4+5+6）
    if (state.drawMode === 10) return 3; // BST 单光眼：仅一条合成曲线
    return 0;
  }

  function applyLayout() {
    var key = layoutKey();
    if (key === _appliedLayout) return;
    _appliedLayout = key;
    if (key === 1) chart.setOption(buildDualOption(), { notMerge: true });
    else if (key === 2) chart.setOption(buildBstOption(), { notMerge: true });
    else if (key === 3) chart.setOption(buildBst10SingleOption(), { notMerge: true });
    else chart.setOption(buildSingleOption(), { notMerge: true });
  }

  function buildSingleOption() {
    return {
      animation: false,
      // 工单2: 隐藏触摸十字光标（顶层 axisPointer 是独立组件，必须单独关闭）
      // 工单5: 隐藏光眼实际值浮层
      tooltip: { show: false },
      axisPointer: { show: false },
      // 工单3: 禁用图例点按显隐曲线
      legend: { data: ['上光眼', '下光眼'], top: 4, textStyle: { fontSize: 11 }, selectedMode: false },
      // 工单1 side-effect: Y 轴已隐藏，left 边距从 48 收窄至 8
      grid: { left: 8, right: 16, top: 32, bottom: 64 },
      dataZoom: [makeZoomInside(0), makeZoomSlider(0)],
      xAxis: makeXAxis(),
      yAxis: makeYAxis(),
      series: [
        makeSeries('上光眼', '#000', { markArea: { silent: true, data: [] } }),
        makeSeries('下光眼', '#e53935')
      ],
      graphic: buildGraphicElements(true)
    };
  }

  function buildDualOption() {
    return {
      animation: false,
      // 工单2: 隐藏触摸十字光标（顶层 axisPointer 是独立组件，必须单独关闭）
      // 工单5: 隐藏光眼实际值浮层
      tooltip: { show: false },
      axisPointer: { show: false },
      // 工单3: 禁用图例点按显隐曲线
      legend: { data: ['上光眼', '下光眼', '下光眼(横跟首)'], top: 4, textStyle: { fontSize: 11 }, selectedMode: false },
      // 工单1 side-effect: Y 轴已隐藏，left 边距从 48 收窄至 8
      grid: [
        { left: 8, right: 16, top: 32, bottom: '55%' },
        { left: 8, right: 16, top: '50%', bottom: 64 }
      ],
      dataZoom: [makeZoomInside([0, 1]), makeZoomSlider([0, 1])],
      xAxis: [makeXAxis(0), makeXAxis(1)],
      yAxis: [makeYAxis(0), makeYAxis(1)],
      series: [
        makeSeries('上光眼', '#000', { xAxisIndex: 0, yAxisIndex: 0, markArea: { silent: true, data: [] } }),
        makeSeries('下光眼', '#e53935', { xAxisIndex: 0, yAxisIndex: 0 }),
        makeSeries('下光眼(横跟首)', '#e53935', { xAxisIndex: 1, yAxisIndex: 1, markArea: { silent: true, data: [] } })
      ],
      graphic: buildGraphicElements(true)
    };
  }

  // BST 模式 10：单图仅显示三色合一曲线，Y 轴 0~765
  function buildBst10SingleOption() {
    return {
      animation: false,
      tooltip: { show: false },
      axisPointer: { show: false },
      legend: { data: ['RGB合'], top: 4, textStyle: { fontSize: 11 }, selectedMode: false },
      grid: { left: 8, right: 16, top: 32, bottom: 100 },
      dataZoom: [makeZoomInside(0), makeZoomSlider(0)],
      xAxis: makeXAxis(),
      yAxis: makeYAxis(undefined, BST_COMBINE_Y_MAX),
      series: [
        makeSeries('RGB合', '#333', { markArea: { silent: true, data: [] } })
      ],
      graphic: buildGraphicElements(true)
    };
  }

  // BST 模式 11：上/下区均为三色合成（0~765），与模式10 同用 bstY 取和
  function buildBstOption() {
    return {
      animation: false,
      tooltip: { show: false },
      axisPointer: { show: false },
      legend: { data: ['上区RGB合', '下区RGB合'], top: 4, textStyle: { fontSize: 11 }, selectedMode: false },
      grid: [
        { left: 8, right: 16, top: 32, bottom: '54%' },
        { left: 8, right: 16, top: '52%', bottom: 64 }
      ],
      dataZoom: [makeZoomInside([0, 1]), makeZoomSlider([0, 1])],
      xAxis: [makeXAxis(0), makeXAxis(1)],
      yAxis: [makeYAxis(0, BST_COMBINE_Y_MAX), makeYAxis(1, BST_COMBINE_Y_MAX)],
      series: [
        makeSeries('上区RGB合', '#333', { xAxisIndex: 0, yAxisIndex: 0, markArea: { silent: true, data: [] } }),
        makeSeries('下区RGB合', '#333', { xAxisIndex: 1, yAxisIndex: 1, markArea: { silent: true, data: [] } })
      ],
      graphic: buildGraphicElements(true)
    };
  }

  // ─── 数据更新 ──────────────────────────────────────────

  /** BST 单/双光眼为 0~1099 共 1100 点；X67 为 config.dataPoints */
  function dataPointCount() {
    if (state.drawMode === 10 || state.drawMode === 11) return 1100;
    return config.dataPoints;
  }

  function indexToMm(i) {
    return config.circumference * i / dataPointCount();
  }

  /** 三通道之和，显示范围 0~765（与合成曲线 Y 轴一致） */
  function bstY(a, b, c, i) {
    var s = (a[i] | 0) + (b[i] | 0) + (c[i] | 0);
    if (s < 0) s = 0;
    if (s > BST_COMBINE_Y_MAX) s = BST_COMBINE_Y_MAX;
    return s;
  }

  function parseMarkPosUmStr(val) {
    var n = parseInt(String(val), 10);
    if (isNaN(n) || n === UDINT_MAX) return null;
    return n / 1000;
  }

  function updateData(group1Bytes, group2Bytes, controlData, extra) {
    if (!chart) return;
    extra = extra || {};
    var g3 = extra.group3 || [];
    var g4 = extra.group4 || [];
    var g5 = extra.group5 || [];
    var g6 = extra.group6 || [];

    if (controlData) {
      var dm = parseInt(controlData.activeDrawMode, 10);
      if (!isNaN(dm) && (dm === 10 || dm === 11)) state.drawMode = dm;
      else if (!isNaN(dm) && dm >= 0 && dm <= 3) state.drawMode = dm;

      var ww = parseFloat(controlData.windowWidth);
      if (!isNaN(ww) && ww > 0) state.windowWidthMm = ww;

      var lp = parseFloat(controlData.curLatchPosition);
      if (!isNaN(lp) && lp > 0) state.lockedPosMm = lp / 1000;
      else state.lockedPosMm = null;

      var pwi = parseFloat(controlData.puWindowInterval);
      if (!isNaN(pwi)) state.puWindowIntervalMm = pwi;

      var circ = parseFloat(controlData.diSImage);
      if (!isNaN(circ) && circ > 0 && circ !== config.circumference) {
        setCircumference(circ);
      }

      state.markSelfMm  = parseMarkPosUmStr(controlData.markSelfPosition);
      state.markFirstMm = parseMarkPosUmStr(controlData.markFirstPosition);
      state.markFrontMm = parseMarkPosUmStr(controlData.markFrontPosition);
      var meb = parseInt(controlData.markEnableBST, 10);
      state.markEnableBst = !isNaN(meb) ? meb : 0;
    }

    applyLayout();

    if (state.drawMode === 10) {
      var n10 = dataPointCount();
      n10 = Math.min(n10, group1Bytes.length, group2Bytes.length, g3.length);
      state.bstStripRgb = { n: n10, r: group1Bytes, g: group2Bytes, b: g3 };
      state.bstStripRgbB = null;
      var sumA = new Array(n10);
      for (var j = 0; j < n10; j++) {
        var x10 = indexToMm(j);
        sumA[j] = [x10, bstY(group1Bytes, group2Bytes, g3, j)];
      }
      chart.setOption({
        series: [
          { data: sumA, markArea: { data: buildMarkAreaData(0) } }
        ],
        graphic: buildGraphicElements(false)
      });
      return;
    }

    if (state.drawMode === 11) {
      // 与模式10 统一：上图 RGB 合 = g1+g2+g3；下图 RGB 合 = g4+g5+g6（同 bstY 取和，0~765）
      var nMax = dataPointCount();
      var nTop = Math.min(nMax, group1Bytes.length, group2Bytes.length, g3.length);
      var nBot = Math.min(nMax, g4.length, g5.length, g6.length);
      state.bstStripRgb = nTop > 0 ? { n: nTop, r: group1Bytes, g: group2Bytes, b: g3 } : null;
      state.bstStripRgbB = nBot > 0 ? { n: nBot, r: g4, g: g5, b: g6 } : null;
      var sumTop = new Array(nTop);
      var sumBot = new Array(nBot);
      var k;
      for (k = 0; k < nTop; k++) {
        var xT = indexToMm(k);
        sumTop[k] = [xT, bstY(group1Bytes, group2Bytes, g3, k)];
      }
      for (k = 0; k < nBot; k++) {
        var xB = indexToMm(k);
        sumBot[k] = [xB, bstY(g4, g5, g6, k)];
      }
      chart.setOption({
        series: [
          { data: sumTop, markArea: { data: buildMarkAreaData(0) } },
          { data: sumBot, markArea: { data: buildMarkAreaData(1) } }
        ],
        graphic: buildGraphicElements(false)
      });
      return;
    }

    state.bstStripRgb = null;
    state.bstStripRgbB = null;

    // 样本数：两路都有数据时与较短一路对齐，避免越界。任一路无数据时，按较长一路取点（见模式2/3 只画单路时另一路长为 0 时否则会 n=0 导致 g1/g2 全空）
    var len1 = group1Bytes.length, len2 = group2Bytes.length;
    var n;
    if (len1 === 0 || len2 === 0) {
      n = Math.min(config.dataPoints, Math.max(len1, len2));
    } else {
      n = Math.min(len1, len2, config.dataPoints);
    }
    var g1 = new Array(n), g2 = new Array(n);
    for (var i = 0; i < n; i++) {
      var x = indexToMm(i);
      g1[i] = [x, i < len1 ? group1Bytes[i] : 0];
      g2[i] = [x, i < len2 ? group2Bytes[i] : 0];
    }
    // 模式1 需要画上下两幅图
    if (state.drawMode === 1) {
      chart.setOption({
        series: [
          { data: g1, markArea: { data: buildMarkAreaData(0) } },
          { data: g2 },
          { data: g2, markArea: { data: buildMarkAreaData(1) } }
        ],
        graphic: buildGraphicElements(false)
      });
    // 模式0、2、3 只需要画一幅图
    } else if (state.drawMode === 0 || state.drawMode === 2 || state.drawMode === 3) {
      var showG1 = (state.drawMode !== 3);
      var showG2 = (state.drawMode !== 2);
      chart.setOption({
        series: [
          { data: showG1 ? g1 : [], markArea: { data: buildMarkAreaData(0) } },
          { data: showG2 ? g2 : [] }
        ],
        graphic: buildGraphicElements(false)
      });
    }
  }

  // ─── 拖拽交互（锁边框跟手）─────────────────────────────

  function clampPos(posMm) {
    if (isNaN(posMm)) return null;
    var halfW = state.windowWidthMm / 2;
    if (posMm < halfW) posMm = halfW;
    if (posMm > config.circumference - halfW) posMm = config.circumference - halfW;
    return Math.round(posMm * 10) / 10;
  }

  // 工单4: 将任意逻辑位置夹紧到轴范围 [0, circumference]。
  // 用于 PLC 来源的 lockedPosMm 等无法在拖拽层约束的场景（贴边回显）。
  function clampToAxis(posMm) {
    if (posMm == null || isNaN(posMm)) return null;
    return Math.max(0, Math.min(config.circumference, posMm));
  }

  // 工单4: drawMode 1 双区拖拽约束 —— 保证上、下两个框永远不出界。
  // 上半区 pos 满足 pos ∈ [halfW, circ-halfW]（已由 clampPos 保证）；
  // 本函数额外约束 pos + offset 也在 [halfW, circ-halfW]，
  // 从而无论 offset 正负，下半区框始终在轴范围内。
  function clampForDual(pos) {
    if (pos == null || isNaN(pos)) return null;
    var halfW  = state.windowWidthMm / 2;
    var offset = state.puWindowIntervalMm;
    var circ   = config.circumference;
    if (offset > 0) {
      // lower center = pos + offset ≤ circ - halfW
      var maxPos = circ - halfW - offset;
      if (maxPos >= halfW) pos = Math.min(pos, maxPos);
    } else if (offset < 0) {
      // lower center = pos + offset ≥ halfW  →  pos ≥ halfW - offset
      var minPos = halfW - offset;
      if (minPos <= circ - halfW) pos = Math.max(pos, minPos);
    }
    return Math.round(pos * 10) / 10;
  }

  function safeConvertX(finder, pt) {
    try {
      var coord = chart.convertFromPixel(finder, pt);
      if (!coord || isNaN(coord[0])) return null;
      return coord[0];
    } catch (e) { return null; }
  }

  function pixelToPosMm(offsetX, offsetY) {
    var pt = [offsetX, offsetY];
    if (!chart) return null;

    if (state.drawMode === 1) {
      if (chart.containPixel({ gridIndex: 0 }, pt)) {
        var x0 = safeConvertX({ gridIndex: 0 }, pt);
        // 工单4: clampForDual 确保下半区框不出界
        return x0 != null ? clampForDual(clampPos(x0)) : null;
      }
      if (chart.containPixel({ gridIndex: 1 }, pt)) {
        var x1 = safeConvertX({ gridIndex: 1 }, pt);
        // 工单4: 从下半区反推 pos，同样通过 clampForDual 确保双区在界内
        return x1 != null ? clampForDual(clampPos(x1 - state.puWindowIntervalMm)) : null;
      }
      return null;
    }

    if (state.drawMode === 11) {
      if (chart.containPixel({ gridIndex: 0 }, pt)) {
        var xb0 = safeConvertX({ gridIndex: 0 }, pt);
        return xb0 != null ? clampPos(xb0) : null;
      }
      if (chart.containPixel({ gridIndex: 1 }, pt)) {
        var xb1 = safeConvertX({ gridIndex: 1 }, pt);
        return xb1 != null ? clampPos(xb1) : null;
      }
      return null;
    }

    if (!chart.containPixel('grid', pt)) return null;
    var x = safeConvertX('grid', pt);
    return x != null ? clampPos(x) : null;
  }

  function onDragStart(params) {
    if (!chart) return;
    var posMm = pixelToPosMm(params.offsetX, params.offsetY);
    if (posMm === null) return;
    drag.active = true;
    drag.lastPosMm = posMm;
    setTouchPosition(posMm);
    if (callbacks.onDrag) callbacks.onDrag(posMm);
  }

  function onDragMove(params) {
    if (!drag.active || !chart) return;
    drag.pendingEvent = params;
    if (!_rafId) {
      _rafId = requestAnimationFrame(function () {
        _rafId = null;
        if (!drag.active || !drag.pendingEvent) return;
        var p = drag.pendingEvent;
        var posMm = pixelToPosMm(p.offsetX, p.offsetY);
        if (posMm === null || posMm === drag.lastPosMm) return;
        drag.lastPosMm = posMm;
        setTouchPosition(posMm);
        if (callbacks.onDrag) callbacks.onDrag(posMm);
      });
    }
  }

  function onDragEnd() {
    if (!drag.active) return;
    drag.active = false;
    drag.pendingEvent = null;
    if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null; }
    if (state.touchPosMm != null && typeof DataService !== 'undefined') {
      DataService.writeCurLatchPosition(Math.round(state.touchPosMm * 1000));
    }
    if (callbacks.onDragEnd) callbacks.onDragEnd(state.touchPosMm);
  }

  function setTouchPosition(posMm) {
    state.touchPosMm = posMm;
    if (!chart) return;
    if (state.drawMode === 1) {
      chart.setOption({
        series: [
          { markArea: { data: buildMarkAreaData(0) } },
          {},
          { markArea: { data: buildMarkAreaData(1) } }
        ],
        graphic: buildGraphicElements(false)
      });
    } else if (state.drawMode === 10) {
      chart.setOption({
        series: [
          { markArea: { data: buildMarkAreaData(0) } }
        ],
        graphic: buildGraphicElements(false)
      });
    } else if (state.drawMode === 11) {
      chart.setOption({
        series: [
          { markArea: { data: buildMarkAreaData(0) } },
          { markArea: { data: buildMarkAreaData(1) } }
        ],
        graphic: buildGraphicElements(false)
      });
    } else {
      chart.setOption({
        series: [{ markArea: { data: buildMarkAreaData(0) } }, {}],
        graphic: buildGraphicElements(false)
      });
    }
  }

  // ─── markArea（触摸框 + 生效框）─────────────────────────

  /** 模式10：与「本/前/首」绘制顺序一致，取第一个可用作锚点，使平移后相对间距不变 */
  function bst10AnchorFromMarks() {
    if ((state.markEnableBst & BSTMK_SELF) && state.markSelfMm != null) return state.markSelfMm;
    if ((state.markEnableBst & BSTMK_FRONT) && state.markFrontMm != null) return state.markFrontMm;
    if ((state.markEnableBst & BSTMK_FIRST) && state.markFirstMm != null) return state.markFirstMm;
    return null;
  }

  /** 模式10 触摸：多个蓝框，数量与启用的 udiMark* 一致，整组平移 d=touch-锚，相对位置与灰框一致 */
  function pushBst10MultiTouchMarkAreas(areas, halfW) {
    var circ = config.circumference;
    var t = state.touchPosMm;
    if (t == null || isNaN(t)) return;
    var b = state.markEnableBst;
    var oneBand = function (centerMm) {
      if (centerMm == null || isNaN(centerMm)) return;
      var x1 = Math.max(0, centerMm - halfW);
      var x2 = Math.min(circ, centerMm + halfW);
      if (x2 <= x1) return;
      areas.push([{ xAxis: x1, itemStyle: BST_TOUCH_MAREA }, { xAxis: x2 }]);
    };
    var anchor = bst10AnchorFromMarks();
    if (anchor == null) {
      var tp = clampToAxis(t);
      if (tp != null) oneBand(tp);
      return;
    }
    var d = t - anchor;
    if ((b & BSTMK_SELF) && state.markSelfMm != null) oneBand(state.markSelfMm + d);
    if ((b & BSTMK_FRONT) && state.markFrontMm != null) oneBand(state.markFrontMm + d);
    if ((b & BSTMK_FIRST) && state.markFirstMm != null) oneBand(state.markFirstMm + d);
  }

  /** 模式11：触摸蓝框仅按本色锚定（与 graphic 中仅绘本色一致；无多色平行带） */
  function pushBst11TouchMarkAreas(areas, halfW) {
    var circ = config.circumference;
    var t = state.touchPosMm;
    if (t == null || isNaN(t)) return;
    if (!((state.markEnableBst & BSTMK_SELF) && state.markSelfMm != null)) {
      var tp = clampToAxis(t);
      if (tp != null) {
        areas.push([{ xAxis: Math.max(0, tp - halfW), itemStyle: BST_TOUCH_MAREA }, { xAxis: Math.min(circ, tp + halfW) }]);
      }
      return;
    }
    var anchor = state.markSelfMm;
    var d = t - anchor;
    var c = anchor + d;
    var x1 = Math.max(0, c - halfW);
    var x2 = Math.min(circ, c + halfW);
    if (x2 > x1) {
      areas.push([{ xAxis: x1, itemStyle: BST_TOUCH_MAREA }, { xAxis: x2 }]);
    }
  }

  function buildMarkAreaData(gridIndex) {
    var areas = [];
    var halfW = state.windowWidthMm / 2;
    var offset = (state.drawMode === 1 && gridIndex === 1) ? state.puWindowIntervalMm : 0;

    var rawTouchPos  = (state.touchPosMm  != null && !isNaN(state.touchPosMm))  ? state.touchPosMm  + offset : null;
    var rawLockedPos = (state.lockedPosMm != null && !isNaN(state.lockedPosMm)) ? state.lockedPosMm + offset : null;
    // 工单4: 对侧边界回显 —— 超轴范围时贴边，使半区内仍能看到指示框
    var touchPos  = clampToAxis(rawTouchPos);
    var lockedPos = clampToAxis(rawLockedPos);

    // 模式10/11：锁标只来自 udiMark*（见 graphic），不绘制 udiCurLatchPosition 的灰带
    if (lockedPos != null && state.drawMode !== 10 && state.drawMode !== 11) {
      areas.push([
        { xAxis: Math.max(0, lockedPos - halfW), itemStyle: { color: BST_LOCK_AREA_FILL, borderWidth: 0 } },
        { xAxis: Math.min(config.circumference, lockedPos + halfW) }
      ]);
    }

    if (state.drawMode === 10 && rawTouchPos != null && !isNaN(rawTouchPos)) {
      if (gridIndex === 0) {
        pushBst10MultiTouchMarkAreas(areas, halfW);
      }
    } else if (state.drawMode === 11 && rawTouchPos != null && !isNaN(rawTouchPos)) {
      if (gridIndex === 0 || gridIndex === 1) {
        pushBst11TouchMarkAreas(areas, halfW);
      }
    } else if (touchPos != null) {
      areas.push([
        { xAxis: Math.max(0, touchPos - halfW), itemStyle: BST_TOUCH_MAREA },
        { xAxis: Math.min(config.circumference, touchPos + halfW) }
      ]);
    }

    return areas;
  }

  // ─── graphic（中心线 + 锁定指示条）─────────────────────

  function px(dataPt, gridIdx) {
    try {
      if (gridIdx !== undefined) {
        return chart.convertToPixel({ gridIndex: gridIdx }, dataPt);
      }
      return chart.convertToPixel('grid', dataPt);
    } catch (e) { return null; }
  }

  function buildGraphicElements(isInit) {
    if (state.drawMode === 1) return buildGraphicDual(isInit);
    if (state.drawMode === 10 || state.drawMode === 11) return buildGraphicBst(isInit);
    return buildGraphicSingle(isInit);
  }

  function makeLineEl(id, strokeColor, dashArr, zVal) {
    return {
      id: id, type: 'line', z: zVal || 100, invisible: true,
      shape: { x1: 0, y1: 0, x2: 0, y2: 0 },
      style: { stroke: strokeColor, lineWidth: 1.5, lineDash: dashArr }
    };
  }

  function makeRectEl(id, fillColor, zVal) {
    return {
      id: id, type: 'rect', z: zVal || 120, invisible: true,
      shape: { x: 0, y: 0, width: 0, height: 0 },
      style: { fill: fillColor }
    };
  }

  function fillCenterLine(el, posMm, axisIdx) {
    var tp = px([posMm, displayYMax()], axisIdx);
    var bp = px([posMm, config.yMin], axisIdx);
    if (tp && bp) {
      el.invisible = false;
      el.shape = { x1: tp[0], y1: tp[1], x2: bp[0], y2: bp[1] };
    }
  }

  function fillRedBar(el, posMm, axisIdx) {
    var halfW = state.windowWidthMm / 2;
    var lL = px([Math.max(0, posMm - halfW), config.yMin], axisIdx);
    var lR = px([Math.min(config.circumference, posMm + halfW), config.yMin], axisIdx);
    if (lL && lR) {
      el.invisible = false;
      el.shape = { x: lL[0], y: lL[1] - 8, width: lR[0] - lL[0], height: 8 };
    }
  }

  /**
   * BST 锁标顶条：本黑/前红/首绿。必须每次写入 fill，且 z 要高于浮动框，避免被同区域浅灰矩形盖住前色、首色。
   */
  function fillBstTopBar(el, posMm, halfW, axisIdx, fillHex) {
    if (posMm == null || isNaN(posMm)) return;
    if (fillHex) el.style.fill = fillHex;
    var lL = px([Math.max(0, posMm - halfW), displayYMax()], axisIdx);
    var lR = px([Math.min(config.circumference, posMm + halfW), displayYMax()], axisIdx);
    if (lL && lR) {
      el.invisible = false;
      el.shape = { x: lL[0], y: lL[1], width: lR[0] - lL[0], height: 8 };
    }
  }

  function buildGraphicSingle(isInit) {
    var touchLine  = makeLineEl('touchCL_0',  '#43a047', [4, 3], 110);
    var lockedLine = makeLineEl('lockedCL_0', '#757575', [3, 3], 100);
    var redBar     = makeRectEl('redBar_0',   '#c62828', 120);

    if (!isInit) {
      if (state.touchPosMm != null)  fillCenterLine(touchLine, state.touchPosMm);
      if (state.lockedPosMm != null) {
        fillCenterLine(lockedLine, state.lockedPosMm);
        fillRedBar(redBar, state.lockedPosMm);
      }
    }

    return [touchLine, lockedLine, redBar];
  }

  function buildGraphicDual(isInit) {
    var offset = state.puWindowIntervalMm;

    var touchLine0  = makeLineEl('touchCL_0',  '#43a047', [4, 3], 110);
    var lockedLine0 = makeLineEl('lockedCL_0', '#757575', [3, 3], 100);
    var redBar0     = makeRectEl('redBar_0',   '#c62828', 120);

    var touchLine1  = makeLineEl('touchCL_1',  '#43a047', [4, 3], 110);
    var lockedLine1 = makeLineEl('lockedCL_1', '#757575', [3, 3], 100);
    var redBar1     = makeRectEl('redBar_1',   '#c62828', 120);

    if (!isInit) {
      if (state.touchPosMm != null) {
        fillCenterLine(touchLine0, state.touchPosMm, 0);
        // 工单4: 下半区触摸指示贴紧轴范围，超出时在对侧边界回显
        fillCenterLine(touchLine1, clampToAxis(state.touchPosMm + offset), 1);
      }
      if (state.lockedPosMm != null) {
        fillCenterLine(lockedLine0, state.lockedPosMm, 0);
        fillRedBar(redBar0, state.lockedPosMm, 0);
        // 工单4: 下半区锁定指示同样贴紧轴范围
        var clamped1 = clampToAxis(state.lockedPosMm + offset);
        fillCenterLine(lockedLine1, clamped1, 1);
        fillRedBar(redBar1, clamped1, 1);
      }
    }

    return [touchLine0, lockedLine0, redBar0, touchLine1, lockedLine1, redBar1];
  }

  function makeBstMarkLineEl(id, strokeColor, dashArr, zVal) {
    return {
      id: id, type: 'line', z: zVal != null ? zVal : 82, invisible: true,
      shape: { x1: 0, y1: 0, x2: 0, y2: 0 },
      style: { stroke: strokeColor, lineWidth: 1, lineDash: dashArr }
    };
  }

  function makeBstFloatRectEl(id) {
    return {
      id: id, type: 'rect', z: 76, invisible: true,
      shape: { x: 0, y: 0, width: 0, height: 0 },
      style: { fill: BST_LOCK_AREA_FILL, lineWidth: 0 }
    };
  }

  /** BST 浮动锁标框：底色与 udiCurLatch 在 0~3 模式下的锁存灰带一致，无描边；本/前/首仅位置来源不同 */
  function drawBstFloatRect(el, posMm, halfW, gridIdx) {
    if (posMm == null || isNaN(posMm)) return;
    el.style.fill = BST_LOCK_AREA_FILL;
    el.style.lineWidth = 0;
    el.style.stroke = 'none';
    var tL = px([Math.max(0, posMm - halfW), displayYMax()], gridIdx);
    var tR = px([Math.min(config.circumference, posMm + halfW), displayYMax()], gridIdx);
    var bL = px([Math.max(0, posMm - halfW), config.yMin], gridIdx);
    if (tL && tR && bL) {
      el.invisible = false;
      el.shape = { x: tL[0], y: tL[1], width: tR[0] - tL[0], height: bL[1] - tL[1] };
    }
  }

  /** 模式11：锁标灰框上沿 grid0 顶、下沿 grid1 底，贯穿两图 */
  function drawBst11FloatSpanGrids(el, posMm, halfW) {
    if (posMm == null || isNaN(posMm)) return;
    el.style.fill = BST_LOCK_AREA_FILL;
    el.style.lineWidth = 0;
    el.style.stroke = 'none';
    var tL = px([Math.max(0, posMm - halfW), displayYMax()], 0);
    var tR = px([Math.min(config.circumference, posMm + halfW), displayYMax()], 0);
    var bL = px([Math.max(0, posMm - halfW), config.yMin], 1);
    if (tL && tR && bL) {
      el.invisible = false;
      el.shape = { x: tL[0], y: tL[1], width: tR[0] - tL[0], height: bL[1] - tL[1] };
    }
  }

  /** 模式11：竖线从 grid0 顶到 grid1 底 */
  function fillBst11VertSpanLine(el, posMm) {
    var t = px([posMm, displayYMax()], 0);
    var b = px([posMm, config.yMin], 1);
    if (t && b) {
      el.invisible = false;
      el.shape = { x1: t[0], y1: t[1], x2: b[0], y2: b[1] };
    }
  }

  function getXAxis0ExtentMm() {
    try {
      var ax0 = chart.getModel().getComponent('xAxis', 0);
      if (ax0 && ax0.axis && ax0.axis.scale) {
        var ex = ax0.axis.scale.getExtent();
        var lo = ex[0];
        var hi = ex[1];
        if (lo > hi) { var t = lo; lo = hi; hi = t; }
        return { min: lo, max: hi };
      }
    } catch (e) { /* 忽略 */ }
    return { min: 0, max: config.circumference };
  }

  /** 某 grid 下沿的像素位置，用于在其下方放 RGB 色带（模式11 两图各一条） */
  function getBstStripLayoutForGrid(gridIdx) {
    if (!chart) return null;
    var bl, br;
    try {
      bl = chart.convertToPixel({ gridIndex: gridIdx }, [0, config.yMin]);
      br = chart.convertToPixel({ gridIndex: gridIdx }, [config.circumference, config.yMin]);
    } catch (e) {
      return null;
    }
    if (!bl || !br || isNaN(bl[0]) || isNaN(br[0])) return null;
    var left = Math.min(bl[0], br[0]);
    var right = Math.max(bl[0], br[0]);
    var w = right - left;
    if (w < 2) return null;
    var yBottom = Math.max(bl[1], br[1]);
    return { left: left, top: yBottom + BST_STRIP_TOP_OFFSET, width: w, height: BST_STRIP_H };
  }

  /** 主图（grid0）下沿 —— 模式10/单带 */
  function getBstStripLayout() {
    return getBstStripLayoutForGrid(0);
  }

  /** @param {Object} [strip] 省略时用 state.bstStripRgb；模式11 下图传 state.bstStripRgbB */
  function buildRgbStripDataURL(layout, strip) {
    var s = strip != null ? strip : state.bstStripRgb;
    if (!s || s.n < 1 || !s.r || !s.g || !s.b) return null;
    var n = s.n;
    var ext = getXAxis0ExtentMm();
    var mm0 = ext.min;
    var mm1 = ext.max;
    if (isNaN(mm0) || isNaN(mm1)) {
      mm0 = 0;
      mm1 = config.circumference;
    }
    var circ = config.circumference;
    if (circ <= 0) return null;
    if (mm1 < mm0) { var t = mm0; mm0 = mm1; mm1 = t; }
    if (mm0 < 0) mm0 = 0;
    if (mm1 > circ) mm1 = circ;
    if (mm1 - mm0 < 1e-6) return null;

    var wPx = Math.max(1, Math.round(layout.width));
    var dpr = (typeof window !== 'undefined' && window.devicePixelRatio) ? window.devicePixelRatio : 1;
    var c = (typeof document !== 'undefined' && document.createElement) ? document.createElement('canvas') : null;
    if (!c) return null;
    c.width = Math.max(1, Math.round(wPx * dpr));
    c.height = Math.max(1, Math.round(BST_STRIP_H * dpr));
    var ctx = c.getContext('2d');
    if (!ctx) return null;
    if (dpr !== 1) { ctx.scale(dpr, dpr); }
    var rArr = s.r, gArr = s.g, bArr = s.b;
    for (var i = 0; i < wPx; i++) {
      var mm = mm0 + (mm1 - mm0) * (i + 0.5) / wPx;
      var idx = Math.floor((mm * n) / circ);
      if (idx < 0) idx = 0;
      if (idx >= n) idx = n - 1;
      var r = (rArr[idx] | 0) & 255;
      var g = (gArr[idx] | 0) & 255;
      var b = (bArr[idx] | 0) & 255;
      ctx.fillStyle = 'rgb(' + r + ',' + g + ',' + b + ')';
      ctx.fillRect(i, 0, 1, BST_STRIP_H);
    }
    try {
      return c.toDataURL('image/png');
    } catch (e2) {
      return null;
    }
  }

  function makeBstRgbStripImage(idStr, pos, strip) {
    var dataUrl = buildRgbStripDataURL(pos, strip);
    if (!dataUrl) return null;
    return {
      id: idStr,
      type: 'image',
      z: 28,
      silent: true,
      left: Math.round(pos.left),
      top: Math.round(pos.top),
      style: {
        image: dataUrl,
        width: pos.width,
        height: BST_STRIP_H
      }
    };
  }

  function makeBstRgbStripGraphic() {
    if (!state.bstStripRgb || state.bstStripRgb.n < 1) return null;
    var pos = getBstStripLayout();
    if (!pos) return null;
    return makeBstRgbStripImage('bst_rgb_strip', pos, state.bstStripRgb);
  }

  /** 模式11：上图色带 = g1~g3，下图色带 = g4~g6 */
  function makeBst11RgbStripGraphics() {
    var out = [];
    if (state.bstStripRgb && state.bstStripRgb.n >= 1) {
      var pos0 = getBstStripLayoutForGrid(0);
      if (pos0) {
        var img0 = makeBstRgbStripImage('bst_rgb_strip_g0', pos0, state.bstStripRgb);
        if (img0) out.push(img0);
      }
    }
    if (state.bstStripRgbB && state.bstStripRgbB.n >= 1) {
      var pos1 = getBstStripLayoutForGrid(1);
      if (pos1) {
        var img1 = makeBstRgbStripImage('bst_rgb_strip_g1', pos1, state.bstStripRgbB);
        if (img1) out.push(img1);
      }
    }
    return out;
  }

  // BST：不画锁存位底部红条；主图下 RGB 色带；三色锁标竖线 + 上沿色条（本黑/前红/首绿）+ 可选浮动窗
  function buildGraphicBst(isInit) {
    var halfW = state.windowWidthMm / 2;

    var touchLine  = makeLineEl('touchCL_bst',  '#43a047', [4, 3], 110);
    var lockedLine = makeLineEl('lockedCL_bst', '#757575', [3, 3], 100);

    var mSelf  = makeBstMarkLineEl('bst_mark_self',  '#6a1b9a', [6, 3], 84);
    var mFirst = makeBstMarkLineEl('bst_mark_first', '#ef6c00', [2, 2], 84);
    var mFront = makeBstMarkLineEl('bst_mark_front', '#1565c0', [4, 2], 84);

    var topSelf  = makeRectEl('bst_top_self',  '#212121', 130);
    var topFront = makeRectEl('bst_top_front', '#c62828', 130);
    var topFirst = makeRectEl('bst_top_first', '#2e7d32', 130);

    var fSelf  = makeBstFloatRectEl('bst_float_self');
    var fFirst = makeBstFloatRectEl('bst_float_first');
    var fFront = makeBstFloatRectEl('bst_float_front');

    if (!isInit) {
      if (state.drawMode === 11) {
        if (state.touchPosMm != null) fillBst11VertSpanLine(touchLine, state.touchPosMm);
      } else {
        if (state.touchPosMm != null) fillCenterLine(touchLine, state.touchPosMm, 0);
      }
      if (state.lockedPosMm != null && state.drawMode !== 10 && state.drawMode !== 11) {
        fillCenterLine(lockedLine, state.lockedPosMm, 0);
      }
      // 模式10 锁标竖线+浮动框+顶条仅跟 udiMark* / usiMarkEnableBST；竖线、上沿色块、浮动窗受位控制
      if (state.drawMode === 10) {
        if ((state.markEnableBst & BSTMK_SELF)  && state.markSelfMm  != null) {
          fillCenterLine(mSelf,  state.markSelfMm,  0);
          drawBstFloatRect(fSelf,  state.markSelfMm,  halfW, 0);
          fillBstTopBar(topSelf,  state.markSelfMm,  halfW, 0, '#212121');
        }
        if ((state.markEnableBst & BSTMK_FRONT) && state.markFrontMm != null) {
          fillCenterLine(mFront, state.markFrontMm, 0);
          drawBstFloatRect(fFront, state.markFrontMm, halfW, 0);
          fillBstTopBar(topFront, state.markFrontMm, halfW, 0, '#c62828');
        }
        if ((state.markEnableBst & BSTMK_FIRST) && state.markFirstMm != null) {
          fillCenterLine(mFirst, state.markFirstMm, 0);
          drawBstFloatRect(fFirst, state.markFirstMm, halfW, 0);
          fillBstTopBar(topFirst, state.markFirstMm, halfW, 0, '#2e7d32');
        }
      } else if (state.drawMode === 11) {
        if ((state.markEnableBst & BSTMK_SELF) && state.markSelfMm != null) {
          fillBst11VertSpanLine(mSelf, state.markSelfMm);
          drawBst11FloatSpanGrids(fSelf, state.markSelfMm, halfW);
          fillBstTopBar(topSelf, state.markSelfMm, halfW, 0, '#212121');
        }
      }
    }

    // 顶条在浮动框之后、z 更高，避免浅灰全高矩形盖住前/首色条
    var out = [touchLine, lockedLine, mSelf, mFirst, mFront, fSelf, fFront, fFirst, topSelf, topFront, topFirst];
    if (!isInit) {
      if (state.drawMode === 11) {
        var strips11 = makeBst11RgbStripGraphics();
        for (var si = 0; si < strips11.length; si++) out.push(strips11[si]);
      } else {
        var strip = makeBstRgbStripGraphic();
        if (strip) out.push(strip);
      }
    }
    return out;
  }

  // ─── 配置更新 ──────────────────────────────────────────

  function setCircumference(mm) {
    if (mm <= 0 || isNaN(mm)) return;
    config.circumference = mm;
    if (!chart) return;
    if (state.drawMode === 1 || state.drawMode === 11) {
      chart.setOption({ xAxis: [{ max: mm, interval: xInterval() }, { max: mm, interval: xInterval() }] });
    } else {
      chart.setOption({ xAxis: { max: mm, interval: xInterval() } });
    }
  }

  // ─── 公开接口 ──────────────────────────────────────────

  return {
    init: init,
    updateData: updateData,
    setTouchPosition: setTouchPosition,
    setCircumference: setCircumference,
    getChart: function () { return chart; },
    getConfig: function () { return config; },
    getState: function () { return state; },
    isDragging: function () { return drag.active; },
    onDrag: function (cb) { callbacks.onDrag = cb; },
    onDragEnd: function (cb) { callbacks.onDragEnd = cb; }
  };
})();
