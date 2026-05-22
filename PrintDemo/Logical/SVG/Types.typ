
TYPE
	SvgTransformField_typ : 	STRUCT
		uiOffset : UINT;
		uiLength : UINT;
	END_STRUCT;

	SvgTransformMap_typ : 	STRUCT
		stEmergencyStyle : SvgTransformField_typ;
		stLine1Style : SvgTransformField_typ;
		stLine2Style : SvgTransformField_typ;
		stFan1Duration : SvgTransformField_typ;
		stFan1Spin : SvgTransformField_typ;
		stRollerUpTranslate : SvgTransformField_typ;
		stRollerDownStyle : SvgTransformField_typ;
		stColorBoxStyle : SvgTransformField_typ;
	END_STRUCT;

	SvgPuCommand_typ : 	STRUCT
		bEmergency : BOOL;
		bLine1Visible : BOOL;
		bLine2Visible : BOOL;
		bFan1Rotate : BOOL;
		bRollerUpDown : BOOL;
		bRollerDownGreen : BOOL;
		bColorBoxYellow : BOOL;
		bManualTestMode : BOOL;
	END_STRUCT;

	SvgPuText_typ : 	STRUCT
		strTemplate : STRING[1000];
		strEmergencyNormal : STRING[16];
		strEmergencyAlarm : STRING[16];
		strDisplayShow : STRING[20];
		strDisplayHide : STRING[20];
		strFan1DurationStop : STRING[8];
		strFan1DurationRun : STRING[8];
		strFan1SpinStop : STRING[16];
		strFan1SpinRun : STRING[16];
		strRollerUpHome : STRING[16];
		strRollerUpDown : STRING[16];
		strRollerDownNormal : STRING[16];
		strRollerDownGreen : STRING[16];
		strColorBoxNormal : STRING[16];
		strColorBoxYellow : STRING[16];
	END_STRUCT;

	SvgPuUnit_typ : 	STRUCT
		stCmd : SvgPuCommand_typ;
		stText : SvgPuText_typ;
		stMap : SvgTransformMap_typ;
		strTransform : STRING[1000];
		bTransformReady : BOOL;
	END_STRUCT;

END_TYPE
