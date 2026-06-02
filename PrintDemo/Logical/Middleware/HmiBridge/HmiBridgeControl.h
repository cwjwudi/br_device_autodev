#ifndef HMIBRIDGE_CONTROL_H
#define HMIBRIDGE_CONTROL_H

static REAL HmiBridgeClampReal(REAL value, REAL minValue, REAL maxValue)
{
	if (value < minValue) {
		return minValue;
	}
	if (value > maxValue) {
		return maxValue;
	}
	return value;
}

static void HmiBridgeInitDemoValues(void)
{
	HMI_MW_U00_Bridge_Cmd_EnableReq = 0;
	HMI_MW_U00_Bridge_Par_Target = 100.0f;
	HMI_MW_U00_Bridge_Par_Mode = 1;

	HMI_MW_U00_Bridge_InOut_Trim = 0.0f;
	HMI_MW_U00_Bridge_InOut_Offset = 0;
	HMI_MW_U00_Bridge_InOut_Recipe = 1;

	stHmiBridgeOld.stInOut.rTrimValue = HMI_MW_U00_Bridge_InOut_Trim;
	stHmiBridgeOld.stInOut.diSharedOffset = HMI_MW_U00_Bridge_InOut_Offset;
	stHmiBridgeOld.stInOut.usiRecipeNo = HMI_MW_U00_Bridge_InOut_Recipe;
	stHmiBridgeCtrl.stInOut = stHmiBridgeOld.stInOut;
}

static void HmiBridgeDemoControlStep(void)
{
	stHmiBridgeCtrl.stOutput.bReady = 1;
	stHmiBridgeCtrl.stOutput.bEnabledEcho = stHmiBridgeCtrl.stInput.bEnableReq;
	stHmiBridgeCtrl.stOutput.rAcceptedTarget =
		HmiBridgeClampReal(stHmiBridgeCtrl.stInput.rTargetValue, -1000.0f, 1000.0f);
	stHmiBridgeCtrl.stOutput.usiAcceptedMode = stHmiBridgeCtrl.stInput.usiModeSelect;

	if (stHmiBridgeCtrl.stOutput.bEnabledEcho) {
		stHmiBridgeCtrl.stOutput.rActualValue =
			stHmiBridgeCtrl.stOutput.rAcceptedTarget + stHmiBridgeCtrl.stInOut.rTrimValue;
	}
	else {
		stHmiBridgeCtrl.stOutput.rActualValue = 0.0f;
	}

	stHmiBridgeCtrl.stOutput.udiCycleCounter++;
}

#endif
