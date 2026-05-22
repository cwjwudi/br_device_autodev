
TYPE
	MiddleInput_typ : 	STRUCT 
		diEchartLockPosition : DINT; (*ECharts 锁标位置返还	*)
	END_STRUCT;
	MiddleOutput_typ : 	STRUCT 
		usiDrawingArr : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT; (*绘图数组数据源*)
		diActualLockPos : DINT; (*实际锁标位置*)
		diActuralLockBoxWidth : DINT; (*实际锁标框宽度	*)
		diLockBoxOffset : DINT; (*锁标窗口偏移*)
		diPuNum : DINT;
	END_STRUCT;
	Middle_Interface_typ : 	STRUCT 
		stInputs : MiddleInput_typ;
		stOutputs : MiddleOutput_typ;
	END_STRUCT;
	HMI_Input_typ : 	STRUCT 
		bCheckedPu : ARRAY[0..16]OF BOOL;
		bMoveCurveLeft : BOOL; (*左平移曲线*)
		bMoveCurveRight : BOOL; (*右平移曲线*)
		bMoveLockBoxLeft : BOOL;
		bMoveLockBoxRight : BOOL;
		diLockBoxWidth : DINT;
		bCmdLatchPos : BOOL;
		bVisMarkIntervalAdd : BOOL;
		bVisMarkIntervalMinus : BOOL;
		bActivePuTeachMode : BOOL;
		bRefreshSimData : BOOL; (*刷新模拟数据（临时）*)
		iSelectFront : INT;
		iSelectFirst : INT;
		bMarkSelectSelfEnable : BOOL; (*本色有效标志*)
		bMarkSelectFrontEnable : BOOL; (*前色有效标志*)
		bMarkSelectFirstEnable : BOOL; (*首色有效标志*)
	END_STRUCT;
	HMI_Output_typ : 	STRUCT 
		diSImage : DINT;
		diPuWindowIntervalmm : DINT; (*当前横向自定义距离值*)
		rPuBiasValue : ARRAY[0..ST_PU_SIZE]OF REAL;
		rPuBiasLow : ARRAY[0..ST_PU_SIZE]OF REAL;
		rPuBiasHigh : ARRAY[0..ST_PU_SIZE]OF REAL;
	END_STRUCT;
	HMI_Interface_typ : 	STRUCT 
		stInputs : HMI_Input_typ; (*HMI 写入 → PLC 读取*)
		stOutputs : HMI_Output_typ; (*PLC 写入 → HMI 读取*)
		stConfig : HMI_Config_typ;
	END_STRUCT;
	HMI_Config_typ : 	STRUCT 
		strPuChartAdr : STRING[80];
	END_STRUCT;
	FromAsp_typ : 	STRUCT 
		udiCurLatchPosition : UDINT; (*色组锁标位置*)
	END_STRUCT;
	ToAsp_typ : 	STRUCT 
		strDataST1 : ARRAY[0..ST_SEP_LEN_MINUS_ONE]OF STRING[ST_SEP_DATA_LEN];
		strDataST2 : ARRAY[0..ST_SEP_LEN_MINUS_ONE]OF STRING[ST_SEP_DATA_LEN];
		strDataST3 : ARRAY[0..ST_SEP_LEN_MINUS_ONE]OF STRING[ST_SEP_DATA_LEN];
		strDataST4 : ARRAY[0..ST_SEP_LEN_MINUS_ONE]OF STRING[ST_SEP_DATA_LEN];
		strDataST5 : ARRAY[0..ST_SEP_LEN_MINUS_ONE]OF STRING[ST_SEP_DATA_LEN];
		strDataST6 : ARRAY[0..ST_SEP_LEN_MINUS_ONE]OF STRING[ST_SEP_DATA_LEN];
		diWindowWidth : DINT; (*锁标窗口宽度*)
		usiCmdLatchPos : USINT; (*锁标指令*)
		udiCurLatchPosition : UDINT; (*色组锁标位置*)
		diPuWindowIntervalmm : DINT; (*当前横向自定义距离值*)
		usiActiveDrawMode : USINT; (*0-代表普通X67双光眼绘图；<br><br>
1-代表X67纵跟前横跟首模式绘图；<br><br>
2-代表X67单标记模式绘图(只画上光眼)<br><br>
3-代表X67单标记模式绘图(只画下光眼)
10-代表BST单眼模式绘图
11-代表BST双眼模式绘图*)
		diSImage : DINT; (*版周数据*)
		udiMarkSelfPosition : UDINT;
		udiMarkFirstPosition : UDINT;
		udiMarkFrontPosition : UDINT;
		usiMarkEnableBST : USINT;
	END_STRUCT;
	Asp_Interface_typ : 	STRUCT 
		stFromAsp : FromAsp_typ;
		stToAsp : ToAsp_typ;
	END_STRUCT;
	ToMain_typ : 	STRUCT  (*mappView -> 后端*)
		usiActivePU : USINT; (*切换当前色组*)
		usiOneMarkMode : USINT; (*单标记开关 gSetPuOneMarkMode*)
		usiCmdLeft : USINT; (*曲线左平移*)
		usiCmdRight : USINT; (*曲线右平移*)
		usiCmdLatchPosLeft : USINT; (*锁标窗口左移*)
		usiCmdLatchPosRight : USINT; (*锁标窗口右移*)
		usiVisMarkIntervalMinus : USINT; (*横向窗口自定义距离值减小*)
		usiVisMarkIntervalAdd : USINT; (*横向窗口自定义距离值增大*)
		usiCmdLatchPos : USINT; (*锁标指令*)
		usiActivePuTeachMode : USINT; (*解锁曲线左右移动*)
		diSideFollowPu1 : DINT; (*横向跟首色开关*)
		diSideWindowDefine : DINT; (*横向窗口自定义开关*)
		diWindowWidth : DINT; (*锁标窗口宽度*)
		udiLatchPosition : ARRAY[0..12]OF UDINT; (*每一色色组锁标位置*)
	END_STRUCT;
	FromMain_typ : 	STRUCT  (*后端 -> mappView*)
		usiActiveDrawMode : USINT; (*0-普通 X67 双光眼;1-纵跟前横跟首;2-单标记模式*)
		diSImage : DINT; (*版周数据*)
		udiActivePuLatchPos : UDINT; (*当前色组锁标位置*)
		diPuWindowIntervalmm : DINT; (*当前横向自定义距离值*)
		diSideWindowInterval : ARRAY[0..12]OF DINT; (*每一色组横向距离自定义距离*)
		usiDataST1 : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT; (*上光眼绘图数据*)
		usiDataST2 : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT; (*下光眼绘图数据*)
		usiDataST3 : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT;
		usiDataST4 : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT;
		usiDataST5 : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT;
		usiDataST6 : ARRAY[0..ST_DATA_LEN_MINUS_ONE]OF USINT;
		diAmrAllMarkPos : ARRAY[0..99]OF DINT; (*自动搜索搜到的有效标位置信息*)
		usiMarkSelectSelf : USINT; (*本色*)
		usiMarkSelectFront : USINT; (*前色*)
		usiMarkSelectFirst : USINT; (*首色*)
	END_STRUCT;
	Main_Interface_typ : 	STRUCT 
		stFromMain : FromMain_typ;
		stToMain : ToMain_typ;
	END_STRUCT;
END_TYPE
