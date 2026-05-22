
#include <bur/plctypes.h>

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

#include "Function.h"


#define SIN_DATA_LENGTH 1000
#define SIN_AMPLITUDE 127.5
#define SIN_OFFSET 127.5
#define MAX_UDINT 4294967295U


#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

void _INIT ProgramInit(void)
{
	gstHmi.stInputs.diLockBoxWidth = 40;
	gstMainInface.stFromMain.diSImage = 600;
	gstMainInface.stToMain.usiActivePU = 0;
	brsstrcpy((UDINT)gstHmi.stConfig.strPuChartAdr, (UDINT)&"http://");
	
	/********************计算IP**************************/
	fbCfgGetIPAddr.enable = 1;
	fbCfgGetIPAddr.pDevice = (UDINT)&"IF2";
	fbCfgGetIPAddr.pIPAddr = (UDINT)strTemp;
	fbCfgGetIPAddr.Len = sizeof(strTemp);
	CfgGetIPAddr(&fbCfgGetIPAddr);
	
	brsstrcat((UDINT)gstHmi.stConfig.strPuChartAdr, (UDINT)strTemp);
	bSimTemp = 1;
}

void _CYCLIC ProgramCyclic(void)
{ 
	/**********************************以下为临时程序***************************************************/	
	if(1 == bSimTemp) {
		/********************** 模拟仿真数据生成 ***************************/	
		if(0 == stOldHmiInput.bRefreshSimData && 1 == gstHmi.stInputs.bRefreshSimData) {
			for(udiIdx = 0; udiIdx < ST_DATA_LEN; udiIdx++) {
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx) / 1000.0);
				gstMainInface.stFromMain.usiDataST1[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
        
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 250) / 1000.0);
				gstMainInface.stFromMain.usiDataST2[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 500) / 1000.0);
				gstMainInface.stFromMain.usiDataST3[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 750) / 1000.0);
				gstMainInface.stFromMain.usiDataST4[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 1000) / 1000.0);
				gstMainInface.stFromMain.usiDataST5[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 1250) / 1000.0);
				gstMainInface.stFromMain.usiDataST6[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
			}
		}
		
		if(0 == stOldHmiInput.bMoveCurveLeft && 1 == gstHmi.stInputs.bMoveCurveLeft) {
			for(udiIdx = 0; udiIdx < ST_DATA_LEN; udiIdx++) {
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx) / 1000.0);
				gstMainInface.stFromMain.usiDataST1[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
        
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 250) / 1000.0);
				gstMainInface.stFromMain.usiDataST2[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 500) / 1000.0);
				gstMainInface.stFromMain.usiDataST3[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 750) / 1000.0);
				gstMainInface.stFromMain.usiDataST4[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 1000) / 1000.0);
				gstMainInface.stFromMain.usiDataST5[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 1250) / 1000.0);
				gstMainInface.stFromMain.usiDataST6[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
			}
    
			udiSinPhase -= 100;
			if(udiSinPhase <= 0) {
				udiSinPhase = 1000;
			}
		}
		
		if(0 == stOldHmiInput.bMoveCurveRight && 1 == gstHmi.stInputs.bMoveCurveRight) {
			for(udiIdx = 0; udiIdx < ST_DATA_LEN; udiIdx++) {
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx) / 1000.0);
				gstMainInface.stFromMain.usiDataST1[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
        
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 250) / 1000.0);
				gstMainInface.stFromMain.usiDataST2[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 500) / 1000.0);
				gstMainInface.stFromMain.usiDataST3[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 750) / 1000.0);
				gstMainInface.stFromMain.usiDataST4[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
				
				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 1000) / 1000.0);
				gstMainInface.stFromMain.usiDataST5[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);

				rSinValue = sin(2.0 * 3.14159265358979 * (REAL)(udiSinPhase + udiIdx + 1250) / 1000.0);
				gstMainInface.stFromMain.usiDataST6[udiIdx] = (USINT)(rSinValue * SIN_AMPLITUDE + SIN_OFFSET);
			}
    
			udiSinPhase += 100;
			if(udiSinPhase >= 1000) {
				udiSinPhase = 0;
			}
		}


		// (Temp) 当前横向自定义距离值，计算
		if(0 == stOldHmiInput.bVisMarkIntervalMinus && 1 == gstHmi.stInputs.bVisMarkIntervalMinus) {
			gstMainInface.stFromMain.diPuWindowIntervalmm = gstMainInface.stFromMain.diPuWindowIntervalmm - 20;
		}
	
		if(0 == stOldHmiInput.bVisMarkIntervalAdd && 1 == gstHmi.stInputs.bVisMarkIntervalAdd) {
			gstMainInface.stFromMain.diPuWindowIntervalmm = gstMainInface.stFromMain.diPuWindowIntervalmm + 20;
		}	
		// 锁标窗口左移与右移动控制，锁定功能
		// 锁定
		if (0 == stOldHmiInput.bCmdLatchPos && 1 == gstHmi.stInputs.bCmdLatchPos) {
			if (gstMainInface.stFromMain.usiActiveDrawMode == 10 || gstMainInface.stFromMain.usiActiveDrawMode == 11) {
				gstMainInface.stFromMain.udiActivePuLatchPos = cal_LatchPos(gstHmi.stInputs.iSelectFront, gstHmi.stInputs.iSelectFirst, gstMainInface.stFromMain.diSImage*1000, gstAspInface.stFromAsp.udiCurLatchPosition);
			} else {
				gstMainInface.stFromMain.udiActivePuLatchPos = gstAspInface.stFromAsp.udiCurLatchPosition;
			}
		}
		// 右移
		if (0 == stOldHmiInput.bMoveLockBoxRight && 1 == gstHmi.stInputs.bMoveLockBoxRight) {
			gstMainInface.stFromMain.udiActivePuLatchPos = gstMainInface.stFromMain.udiActivePuLatchPos + 1000;
		}
		// 左移
		if (0 == stOldHmiInput.bMoveLockBoxLeft && 1 == gstHmi.stInputs.bMoveLockBoxLeft) {
			gstMainInface.stFromMain.udiActivePuLatchPos = gstMainInface.stFromMain.udiActivePuLatchPos - 1000;

		}
		// 限幅
		if (gstMainInface.stFromMain.udiActivePuLatchPos > (UDINT)gstMainInface.stFromMain.diSImage * 1000) {
			gstMainInface.stFromMain.udiActivePuLatchPos = (UDINT)gstMainInface.stFromMain.diSImage * 1000;
		}
		if (gstMainInface.stFromMain.udiActivePuLatchPos < 0) {
			gstMainInface.stFromMain.udiActivePuLatchPos = 0;
		}

		// 计算BST锁标偏移
		if (gstMainInface.stFromMain.usiActiveDrawMode == 10 || gstMainInface.stFromMain.usiActiveDrawMode == 11) {
			cal_BST_Idx(gstHmi.stInputs.iSelectFront, gstHmi.stInputs.iSelectFirst, 0, &gstMainInface.stFromMain.usiMarkSelectFront, &gstMainInface.stFromMain.usiMarkSelectFirst, &gstMainInface.stFromMain.usiMarkSelectSelf);

		}
	}
	/*******************************临时程序到此为止*****************************************************/				

	
	/********************** 色组选择换算 ***************************/
	// gstMiddle.stOutputs.diPuNum
	for(udiIdx = 0; udiIdx < sizeof(gstHmi.stInputs.bCheckedPu)/sizeof(gstHmi.stInputs.bCheckedPu[0]); udiIdx ++) {
		if (1 == gstHmi.stInputs.bCheckedPu[udiIdx] && 0 == stOldHmiInput.bCheckedPu[udiIdx]) {
			brsmemset((UDINT)gstHmi.stInputs.bCheckedPu,0 , sizeof(gstHmi.stInputs.bCheckedPu));
			gstMainInface.stToMain.usiActivePU = (USINT)udiIdx;
		}
	}
	/********************** 绘图数据转换 ***************************/	
	
	if (0 == gstMainInface.stFromMain.usiActiveDrawMode || 1 == gstMainInface.stFromMain.usiActiveDrawMode) {
		// 1号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST1, ST_DATA_LEN, strHexStrBuffer);
		// bytes_to_hex_string(gstMainInface.stFromMain.usiDataST1, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST1[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 2号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST2, ST_DATA_LEN, strHexStrBuffer);
		// bytes_to_hex_string(gstMainInface.stFromMain.usiDataST2, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST2[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 3 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST3[udiIdx][0] = '\0';
		}
		// 4 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST4[udiIdx][0] = '\0';
		}
		// 5 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST5[udiIdx][0] = '\0';
		}
		// 6 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST6[udiIdx][0] = '\0';
		}
	} 	else if(2 == gstMainInface.stFromMain.usiActiveDrawMode) {
		// 1号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST1, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST1[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 2 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST2[udiIdx][0] = '\0';
		}
		// 3 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST3[udiIdx][0] = '\0';
		}
		// 4 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST4[udiIdx][0] = '\0';
		}
		// 5 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST5[udiIdx][0] = '\0';
		}
		// 6 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST6[udiIdx][0] = '\0';
		}
	} 	else if (3 == gstMainInface.stFromMain.usiActiveDrawMode) {
		// 1 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST1[udiIdx][0] = '\0';
		}
		// 2 号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST2, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST2[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 3 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST3[udiIdx][0] = '\0';
		}
		// 4 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST4[udiIdx][0] = '\0';
		}
		// 5 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST5[udiIdx][0] = '\0';
		}
		// 6号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST6[udiIdx][0] = '\0';
		}			
	} else if (10 == gstMainInface.stFromMain.usiActiveDrawMode || 11 == gstMainInface.stFromMain.usiActiveDrawMode) {
		// 1号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST1, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST1[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 2号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST2, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST2[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}	
		// 3号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST3, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST3[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 4号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST4, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST4[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 5号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST5, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST5[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}
		// 6号传感器数据
		uint8_to_base64_string(gstMainInface.stFromMain.usiDataST6, ST_DATA_LEN, strHexStrBuffer);
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			brsmemcpy((UDINT)gstAspInface.stToAsp.strDataST6[udiIdx] , (UDINT)&strHexStrBuffer[ST_SEP_DATA_LEN * udiIdx], ST_SEP_DATA_LEN);
		}	
	} else {
		// 1 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST1[udiIdx][0] = '\0';
		}
		// 2 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST2[udiIdx][0] = '\0';
		}
		// 3 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST3[udiIdx][0] = '\0';
		}
		// 4 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST4[udiIdx][0] = '\0';
		}
		// 5 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST5[udiIdx][0] = '\0';
		}
		// 6 号传感器数据
		for(udiIdx = 0; udiIdx < ST_SEP_LEN; udiIdx ++) {
			gstAspInface.stToAsp.strDataST6[udiIdx][0] = '\0';
		}
	}
	
	/********************** 编码器数据生成 ***************************/	
	for (udiIdx = 0; udiIdx < ST_PU_SIZE; udiIdx++) {
		gstHmi.stOutputs.rPuBiasValue[udiIdx] = random_real(-5.0, 5.0);
		gstHmi.stOutputs.rPuBiasHigh[udiIdx] = 20.0;
		gstHmi.stOutputs.rPuBiasLow[udiIdx] = -20.0;
	}

	/********************** 与ASP层的通信交互 ***************************/	
	gstAspInface.stToAsp.udiCurLatchPosition   = gstMainInface.stFromMain.udiActivePuLatchPos;
	gstAspInface.stToAsp.usiCmdLatchPos        = (USINT)gstHmi.stInputs.bCmdLatchPos;
	gstAspInface.stToAsp.diWindowWidth         = gstHmi.stInputs.diLockBoxWidth;
	gstAspInface.stToAsp.diPuWindowIntervalmm  = gstMainInface.stFromMain.diPuWindowIntervalmm;
	gstAspInface.stToAsp.usiActiveDrawMode	   = gstMainInface.stFromMain.usiActiveDrawMode;
	gstAspInface.stToAsp.diSImage			   = gstMainInface.stFromMain.diSImage;
	
	// BST 标记位置计算
	if ((0 == stOldHmiInput.bCmdLatchPos && 1 == gstHmi.stInputs.bCmdLatchPos)
		&& (gstMainInface.stFromMain.usiActiveDrawMode == 10 || gstMainInface.stFromMain.usiActiveDrawMode == 11)) {
		if (gstHmi.stInputs.bMarkSelectSelfEnable) {
			gstAspInface.stToAsp.udiMarkSelfPosition = 
			(gstMainInface.stFromMain.udiActivePuLatchPos + (UDINT)gstMainInface.stFromMain.usiMarkSelectSelf  * BST_SEG_UM) % (UDINT)(gstMainInface.stFromMain.diSImage * 1000);
		}else {
			gstAspInface.stToAsp.udiMarkSelfPosition = MAX_UDINT;	
		}

		if (gstHmi.stInputs.bMarkSelectFirstEnable) {
			gstAspInface.stToAsp.udiMarkFirstPosition = 
			(gstMainInface.stFromMain.udiActivePuLatchPos + (UDINT)gstMainInface.stFromMain.usiMarkSelectFirst * BST_SEG_UM) % (UDINT)(gstMainInface.stFromMain.diSImage * 1000);
		}else {
			gstAspInface.stToAsp.udiMarkFirstPosition = MAX_UDINT;	
		}

		if (gstHmi.stInputs.bMarkSelectFrontEnable) {
			gstAspInface.stToAsp.udiMarkFrontPosition = 
			(gstMainInface.stFromMain.udiActivePuLatchPos + (UDINT)gstMainInface.stFromMain.usiMarkSelectFront * BST_SEG_UM) % (UDINT)(gstMainInface.stFromMain.diSImage * 1000);
		}else {
			gstAspInface.stToAsp.udiMarkFrontPosition = MAX_UDINT;	
		}
	}

	// 计算 usiMarkEnableBST：按位操作
	// 最低位 (Bit 0) 对应 Self (bMarkSelectSelfEnable)
	// 次低位 (Bit 1) 对应 Front (bMarkSelectFrontEnable)
	// 第 2 位 (Bit 2) 对应 First (bMarkSelectFirstEnable)
	gstAspInface.stToAsp.usiMarkEnableBST = 0;
	if (gstHmi.stInputs.bMarkSelectSelfEnable) {
		gstAspInface.stToAsp.usiMarkEnableBST |= 0x01; // Set Bit 0
	}
	if (gstHmi.stInputs.bMarkSelectFrontEnable) {
		gstAspInface.stToAsp.usiMarkEnableBST |= 0x02; // Set Bit 1
	}
	if (gstHmi.stInputs.bMarkSelectFirstEnable) {
		gstAspInface.stToAsp.usiMarkEnableBST |= 0x04; // Set Bit 2
	}

	
	/********************** 与主控的通信交互 ***************************/	
	gstMainInface.stToMain.usiCmdLatchPos      = (USINT)gstHmi.stInputs.bCmdLatchPos;
	gstMainInface.stToMain.diWindowWidth       = gstHmi.stInputs.diLockBoxWidth;
	gstMainInface.stToMain.usiCmdLeft          = (USINT)gstHmi.stInputs.bMoveCurveLeft;
	gstMainInface.stToMain.usiCmdRight         = (USINT)gstHmi.stInputs.bMoveCurveRight;
	gstMainInface.stToMain.usiCmdLatchPosLeft  = (USINT)gstHmi.stInputs.bMoveLockBoxLeft;
	gstMainInface.stToMain.usiCmdLatchPosRight = (USINT)gstHmi.stInputs.bMoveLockBoxRight;
	gstMainInface.stToMain.usiVisMarkIntervalAdd   = (USINT)gstHmi.stInputs.bVisMarkIntervalAdd;
	gstMainInface.stToMain.usiVisMarkIntervalMinus = (USINT)gstHmi.stInputs.bVisMarkIntervalMinus;
	gstMainInface.stToMain.usiActivePuTeachMode = (USINT)gstHmi.stInputs.bActivePuTeachMode;
	gstMainInface.stFromMain.usiActiveDrawMode;  // 绘图模式

	// 触发锁标按钮后，将Asp读取到的位置
	if (0 == stOldHmiInput.bCmdLatchPos && 1 == gstHmi.stInputs.bCmdLatchPos) {
		gstMainInface.stToMain.udiLatchPosition[gstMainInface.stToMain.usiActivePU] = gstAspInface.stFromAsp.udiCurLatchPosition;
		if (gstMainInface.stFromMain.usiActiveDrawMode == 10 || gstMainInface.stFromMain.usiActiveDrawMode == 11) {

			gstMainInface.stToMain.udiLatchPosition[gstMainInface.stToMain.usiActivePU] = gstAspInface.stFromAsp.udiCurLatchPosition 
				+ (UDINT)(find_min_of_three(gstHmi.stInputs.iSelectFront, gstHmi.stInputs.iSelectFirst, 0) * (INT)BST_SEG_UM);
		}
	}

	gstHmi.stOutputs.diSImage = gstMainInface.stFromMain.diSImage;
	gstHmi.stOutputs.diPuWindowIntervalmm = gstMainInface.stFromMain.diPuWindowIntervalmm;

	

	/********************** Old ***************************/	
	brsmemcpy((UDINT)&stOldHmiInput, (UDINT)&gstHmi.stInputs, sizeof(gstHmi.stInputs));

}

void _EXIT ProgramExit(void)
{

}

