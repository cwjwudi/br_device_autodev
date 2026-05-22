// js/dataService.js

/**
 * 数据服务模块 - 负责从 PLC 读取数据
 * 数据来源：color01.json.asp
 */

var DataService = (function() {
  
  // 配置常量
  var CONFIG = {
    // 第一组数据字段 (strDataST1[0-5])
    GROUP1_FIELDS: [
      'strHex00', 'strHex01', 'strHex02', 'strHex03', 'strHex04',
      'strHex05'
    ],
    
    // 第二组数据字段 (strDataST2[0-5])
    GROUP2_FIELDS: [
      'strHex10', 'strHex11', 'strHex12', 'strHex13', 'strHex14',
      'strHex15'
    ],
    
    // 第三组数据字段 (strDataST3[0-5])
    GROUP3_FIELDS: [
      'strHex20', 'strHex21', 'strHex22', 'strHex23', 'strHex24',
      'strHex25'
    ],
    
    // 第四~六组：PLC strDataST4~6 → color01 strHex30~55；与 group1~3 同一接口。模式11 下图 RGB 合与下图色带用 group4~6（上图与模式10 同为 group1~3）
    GROUP4_FIELDS: [
      'strHex30', 'strHex31', 'strHex32', 'strHex33', 'strHex34',
      'strHex35'
    ],
    
    GROUP5_FIELDS: [
      'strHex40', 'strHex41', 'strHex42', 'strHex43', 'strHex44',
      'strHex45'
    ],
    
    GROUP6_FIELDS: [
      'strHex50', 'strHex51', 'strHex52', 'strHex53', 'strHex54',
      'strHex55'
    ],
    
    // 其他控制字段
    CONTROL_FIELDS: {
      WINDOW_WIDTH: 'diWindowWidth',           // 窗口宽度
      CMD_LATCH_POS: 'usiCmdLatchPos',         // 命令锁存位置
      CUR_LATCH_POSITION: 'udiCurLatchPosition', // 当前锁存位置
      PU_WINDOW_INTERVAL: 'diPuWindowIntervalmm', // 窗口间隔
      ACTIVE_DRAW_MODE: 'usiActiveDrawMode', // 激活绘制模式
      DI_S_IMAGE: 'diSImage', // 版周数据
      MARK_SELF_POSITION: 'udiMarkSelfPosition', // 本色
      MARK_FIRST_POSITION: 'udiMarkFirstPosition', // 首色
      MARK_FRONT_POSITION: 'udiMarkFrontPosition', // 前色
      MARK_ENABLE_BST: 'usiMarkEnableBST' // 标记启用 BST
    },
    
    // 数据填充长度
    PAD_LENGTH: 250,
    
    // 请求超时时间 (ms)
    TIMEOUT: 5000,
    
    // 重试间隔 (ms)
    RETRY_INTERVAL: 3000
  };

  // 内部状态
  var lastWindowWidth = null;
  var dataCallback = null;
  var errorCallback = null;
  var pollTimerId = null;
  var isPollingStopped = false;

  /**
   * Base64 字符串转 Uint8Array
   * @param {string} base64Str - Base64 编码的字符串
   * @returns {number[]} 字节数组
   */
  function base64ToBytes(base64Str) {
    if (!base64Str || typeof base64Str !== 'string') {
      return [];
    }
    
    // 移除可能存在的空白字符
    var cleanStr = base64Str.replace(/\s/g, '');
    
    // 如果清理后为空字符串，返回空数组
    if (cleanStr === '') {
      return [];
    }
    
    // Base64 解码
    var binaryString = atob(cleanStr);
    
    // 转换为字节数组
    var bytes = [];
    for (var i = 0; i < binaryString.length; i++) {
      bytes.push(binaryString.charCodeAt(i) & 0xFF);
    }
    
    return bytes;
  }

  /**
   * 十六进制字符串转字节数组
   * @param {string} hexStr - 十六进制字符串
   * @returns {number[]} 字节数组
   */
  function hexStringToBytes(hexStr) {
    if (hexStr.length % 2 !== 0) {
      throw new Error('十六进制字符串长度必须为偶数，当前长度：' + hexStr.length);
    }
    const bytes = [];
    for (let i = 0; i < hexStr.length; i += 2) {
      const byteStr = hexStr.substr(i, 2);
      const value = parseInt(byteStr, 16);
      if (isNaN(value)) {
        throw new Error('无效的十六进制字符：' + byteStr);
      }
      bytes.push(value);
    }
    return bytes;
  }

  /**
   * 合并多个十六进制字符串
   * @param {string[]} strings - 字符串数组
   * @returns {string} 合并后的字符串
   */
  function mergeHexStrings(strings) {
    return strings.join('');
  }

  /**
   * 填充字符串到指定长度
   * @param {string} str - 原字符串
   * @param {number} len - 目标长度
   * @returns {string} 填充后的字符串
   */
  function padString(str, len) {
    if (typeof str !== 'string') str = '';
    if (str.length < len) {
      return str.padEnd(len, '0');
    }
    return str.substring(0, len);
  }

  /**
   * 验证响应数据完整性
   * @param {Object} resp - 响应对象
   * @param {string[]} fields - 需要验证的字段列表
   */
  function validateResponse(resp, fields) {
    for (const field of fields) {
      if (!resp.hasOwnProperty(field) || typeof resp[field] !== 'string') {
        throw new Error(`缺少或无效的字段：${field}`);
      }
    }
  }

  /**
   * 处理数据并回调
   * @param {Object} resp - AJAX 响应数据
   */
  function processData(resp) {
    try {
      // 验证所有必需字段
      var allFields = []
        .concat(CONFIG.GROUP1_FIELDS)
        .concat(CONFIG.GROUP2_FIELDS)
        .concat(CONFIG.GROUP3_FIELDS)
        .concat(CONFIG.GROUP4_FIELDS)
        .concat(CONFIG.GROUP5_FIELDS)
        .concat(CONFIG.GROUP6_FIELDS);
      validateResponse(resp, allFields);

      // 处理 6 组数据 - 拼接后 Base64 解码
      var group1HexString = mergeHexStrings(CONFIG.GROUP1_FIELDS.map(function(f) { return resp[f]; }));
      var group2HexString = mergeHexStrings(CONFIG.GROUP2_FIELDS.map(function(f) { return resp[f]; }));
      var group3HexString = mergeHexStrings(CONFIG.GROUP3_FIELDS.map(function(f) { return resp[f]; }));
      var group4HexString = mergeHexStrings(CONFIG.GROUP4_FIELDS.map(function(f) { return resp[f]; }));
      var group5HexString = mergeHexStrings(CONFIG.GROUP5_FIELDS.map(function(f) { return resp[f]; }));
      var group6HexString = mergeHexStrings(CONFIG.GROUP6_FIELDS.map(function(f) { return resp[f]; }));
      
      var group1Data = base64ToBytes(group1HexString);
      var group2Data = base64ToBytes(group2HexString);
      var group3Data = base64ToBytes(group3HexString);
      var group4Data = base64ToBytes(group4HexString);
      var group5Data = base64ToBytes(group5HexString);
      var group6Data = base64ToBytes(group6HexString);

      var controlData = {
        windowWidth: resp[CONFIG.CONTROL_FIELDS.WINDOW_WIDTH],
        cmdLatchPos: resp[CONFIG.CONTROL_FIELDS.CMD_LATCH_POS],
        curLatchPosition: resp[CONFIG.CONTROL_FIELDS.CUR_LATCH_POSITION],
        puWindowInterval: resp[CONFIG.CONTROL_FIELDS.PU_WINDOW_INTERVAL],
        activeDrawMode: resp[CONFIG.CONTROL_FIELDS.ACTIVE_DRAW_MODE],
        diSImage: resp[CONFIG.CONTROL_FIELDS.DI_S_IMAGE],
        markSelfPosition: resp[CONFIG.CONTROL_FIELDS.MARK_SELF_POSITION],
        markFirstPosition: resp[CONFIG.CONTROL_FIELDS.MARK_FIRST_POSITION],
        markFrontPosition: resp[CONFIG.CONTROL_FIELDS.MARK_FRONT_POSITION],
        markEnableBST: resp[CONFIG.CONTROL_FIELDS.MARK_ENABLE_BST]
      };
      lastWindowWidth = controlData.windowWidth;

      // 打印所有控制数据 (controlData)
      // console.log("控制数据 (controlData):", controlData);
      var result = {
        group1Data: group1Data,
        group2Data: group2Data,
        group3Data: group3Data,
        group4Data: group4Data,
        group5Data: group5Data,
        group6Data: group6Data,
        controlData: controlData,
        rawResponse: resp
      };
      if (dataCallback) {
        dataCallback(result);
      }
      return result;
    } catch (e) {
      console.error("数据处理失败:", e);
      if (errorCallback) {
        errorCallback(e);
      }
      throw e;
    }
  }

  /**
   * 解析单次响应（供测试页等使用，不依赖回调）
   * @param {Object} resp - AJAX 响应数据
   * @returns {Object} { group1Data, group2Data, group3Data, group4Data, group5Data, group6Data, controlData, rawResponse }
   */
  function parseResponse(resp) {
    var allFields = []
      .concat(CONFIG.GROUP1_FIELDS)
      .concat(CONFIG.GROUP2_FIELDS)
      .concat(CONFIG.GROUP3_FIELDS)
      .concat(CONFIG.GROUP4_FIELDS)
      .concat(CONFIG.GROUP5_FIELDS)
      .concat(CONFIG.GROUP6_FIELDS);
    validateResponse(resp, allFields);
    
    // 拼接后 Base64 解码
    var group1HexString = mergeHexStrings(CONFIG.GROUP1_FIELDS.map(function(f) { return resp[f]; }));
    var group2HexString = mergeHexStrings(CONFIG.GROUP2_FIELDS.map(function(f) { return resp[f]; }));
    var group3HexString = mergeHexStrings(CONFIG.GROUP3_FIELDS.map(function(f) { return resp[f]; }));
    var group4HexString = mergeHexStrings(CONFIG.GROUP4_FIELDS.map(function(f) { return resp[f]; }));
    var group5HexString = mergeHexStrings(CONFIG.GROUP5_FIELDS.map(function(f) { return resp[f]; }));
    var group6HexString = mergeHexStrings(CONFIG.GROUP6_FIELDS.map(function(f) { return resp[f]; }));
    
    var group1Data = base64ToBytes(group1HexString);
    var group2Data = base64ToBytes(group2HexString);
    var group3Data = base64ToBytes(group3HexString);
    var group4Data = base64ToBytes(group4HexString);
    var group5Data = base64ToBytes(group5HexString);
    var group6Data = base64ToBytes(group6HexString);
    
    return {
      group1Data: group1Data,
      group2Data: group2Data,
      group3Data: group3Data,
      group4Data: group4Data,
      group5Data: group5Data,
      group6Data: group6Data,
      controlData: {
        windowWidth: resp[CONFIG.CONTROL_FIELDS.WINDOW_WIDTH],
        cmdLatchPos: resp[CONFIG.CONTROL_FIELDS.CMD_LATCH_POS],
        curLatchPosition: resp[CONFIG.CONTROL_FIELDS.CUR_LATCH_POSITION],
        puWindowInterval: resp[CONFIG.CONTROL_FIELDS.PU_WINDOW_INTERVAL],
        activeDrawMode: resp[CONFIG.CONTROL_FIELDS.ACTIVE_DRAW_MODE],
        diSImage: resp[CONFIG.CONTROL_FIELDS.DI_S_IMAGE],
        markSelfPosition: resp[CONFIG.CONTROL_FIELDS.MARK_SELF_POSITION],
        markFirstPosition: resp[CONFIG.CONTROL_FIELDS.MARK_FIRST_POSITION],
        markFrontPosition: resp[CONFIG.CONTROL_FIELDS.MARK_FRONT_POSITION],
        markEnableBST: resp[CONFIG.CONTROL_FIELDS.MARK_ENABLE_BST]
      },
      rawResponse: resp
    };
  }

  /**
   * 写入当前锁存位置到 PLC
   * @param {number|string} position - 位置值
   */
  function writeCurLatchPosition(position) {
    try {
      if (typeof pvAccess !== 'undefined') {
        pvAccess.WritePV("gstAspInface.stFromAsp.udiCurLatchPosition", position.toString());
        console.log("已写入位置值：" + position);
      } else {
        console.warn("pvAccess 未定义，无法写入");
      }
    } catch (error) {
      console.error("写入 PV 失败:", error);
      throw error;
    }
  }

  /**
   * 启动数据轮询
   * @param {string} dataUrl - 数据源 URL（如：'asp/color01.json.asp'）
   * @param {Function} onData - 数据回调函数
   * @param {Function} onError - 错误回调函数（可选）
   */
  function startPolling(dataUrl, onData, onError) {
    if (!dataUrl || !onData) {
      throw new Error("dataUrl 和 onData 参数不能为空");
    }
    isPollingStopped = false;
    dataCallback = onData;
    errorCallback = onError || function(err) { console.error("数据获取错误:", err); };

    function fetch() {
      $.ajax({
        url: dataUrl + '?' + Date.now(),
        dataType: 'json',
        cache: false,
        timeout: CONFIG.TIMEOUT,
        success: function(resp) {
          try {
            processData(resp);
            if (!isPollingStopped) {
              pollTimerId = setTimeout(fetch, 1000);
            }
          } catch (e) {
            if (!isPollingStopped) {
              pollTimerId = setTimeout(fetch, CONFIG.RETRY_INTERVAL);
            }
          }
        },
        error: function(xhr, status, error) {
          console.error("AJAX 失败:", { status, error, xhr });
          if (errorCallback) {
            errorCallback(new Error("AJAX 失败：" + status));
          }
          if (!isPollingStopped) {
            pollTimerId = setTimeout(fetch, CONFIG.RETRY_INTERVAL);
          }
        }
      });
    }

    fetch();
  }

  /**
   * 停止轮询（供测试页暂停/恢复用）
   */
  function stopPolling() {
    isPollingStopped = true;
    if (pollTimerId) {
      clearTimeout(pollTimerId);
      pollTimerId = null;
    }
  }

  /**
   * 获取最新的窗口宽度
   * @returns {any} 窗口宽度值
   */
  function getLastWindowWidth() {
    return lastWindowWidth;
  }

  /**
   * 重置状态
   */
  function reset() {
    lastWindowWidth = null;
    dataCallback = null;
    errorCallback = null;
  }

  // 公开接口
  return {
    startPolling: startPolling,
    stopPolling: stopPolling,
    parseResponse: parseResponse,
    getLastWindowWidth: getLastWindowWidth,
    reset: reset,
    writeCurLatchPosition: writeCurLatchPosition,
    
    // 工具函数也暴露出来供外部使用
    utils: {
      base64ToBytes: base64ToBytes,
      hexStringToBytes: hexStringToBytes,
      mergeHexStrings: mergeHexStrings,
      padString: padString
    },
    
    // 配置信息
    config: CONFIG
  };
})();