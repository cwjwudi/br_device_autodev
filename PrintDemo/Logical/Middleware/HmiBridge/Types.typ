
TYPE
	HmiBridgeInput_typ : 	STRUCT
		bEnableReq : BOOL;
		rTargetValue : REAL;
		usiModeSelect : USINT;
	END_STRUCT;

	HmiBridgeOutput_typ : 	STRUCT
		bReady : BOOL;
		bEnabledEcho : BOOL;
		rAcceptedTarget : REAL;
		rActualValue : REAL;
		usiAcceptedMode : USINT;
		udiCycleCounter : UDINT;
	END_STRUCT;

	HmiBridgeInOut_typ : 	STRUCT
		rTrimValue : REAL;
		diSharedOffset : DINT;
		usiRecipeNo : USINT;
	END_STRUCT;

	HmiBridgeCtrl_typ : 	STRUCT
		stInput : HmiBridgeInput_typ;
		stOutput : HmiBridgeOutput_typ;
		stInOut : HmiBridgeInOut_typ;
	END_STRUCT;

	HmiBridgeOld_typ : 	STRUCT
		stInOut : HmiBridgeInOut_typ;
	END_STRUCT;
END_TYPE
