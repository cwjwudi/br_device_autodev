
#include <bur/plctypes.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

#define HMI_TO_CTRL(clientVar, servVar) \
do {                                    \
	(servVar) = (clientVar);            \
} while (0)

#define CTRL_TO_HMI(clientVar, servVar) \
do {                                    \
	(clientVar) = (servVar);            \
} while (0)

#define READ_WRITE(clientVar, clientOld, servVar) \
do {                                              \
	if ((clientVar) != (clientOld)) {             \
		(servVar) = (clientVar);                  \
		(clientOld) = (clientVar);                \
	}                                             \
	else if ((clientVar) != (servVar)) {          \
		(clientVar) = (servVar);                  \
		(clientOld) = (servVar);                  \
	}                                             \
} while (0)

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

static void HmiBridgeSyncRegisteredVariables(void)
{
	/* INPUT: HMI writes request/config values, PLC control reads them. */
	HMI_TO_CTRL(HMI_MW_U00_Bridge_Cmd_EnableReq,
		stHmiBridgeCtrl.stInput.bEnableReq);
	HMI_TO_CTRL(HMI_MW_U00_Bridge_Par_Target,
		stHmiBridgeCtrl.stInput.rTargetValue);
	HMI_TO_CTRL(HMI_MW_U00_Bridge_Par_Mode,
		stHmiBridgeCtrl.stInput.usiModeSelect);

	/* OUTPUT: PLC control writes status/feedback values, HMI reads them. */
	CTRL_TO_HMI(HMI_MW_U00_Bridge_Sts_Ready,
		stHmiBridgeCtrl.stOutput.bReady);
	CTRL_TO_HMI(HMI_MW_U00_Bridge_Sts_Enabled,
		stHmiBridgeCtrl.stOutput.bEnabledEcho);
	CTRL_TO_HMI(HMI_MW_U00_Bridge_Act_Target,
		stHmiBridgeCtrl.stOutput.rAcceptedTarget);
	CTRL_TO_HMI(HMI_MW_U00_Bridge_Act_Value,
		stHmiBridgeCtrl.stOutput.rActualValue);
	CTRL_TO_HMI(HMI_MW_U00_Bridge_Sts_Mode,
		stHmiBridgeCtrl.stOutput.usiAcceptedMode);
	CTRL_TO_HMI(HMI_MW_U00_Bridge_Diag_Cycle,
		stHmiBridgeCtrl.stOutput.udiCycleCounter);

	/* IN_OUT: whichever side changed since last cycle wins the sync. */
	READ_WRITE(HMI_MW_U00_Bridge_InOut_Trim,
		stHmiBridgeOld.stInOut.rTrimValue,
		stHmiBridgeCtrl.stInOut.rTrimValue);
	READ_WRITE(HMI_MW_U00_Bridge_InOut_Offset,
		stHmiBridgeOld.stInOut.diSharedOffset,
		stHmiBridgeCtrl.stInOut.diSharedOffset);
	READ_WRITE(HMI_MW_U00_Bridge_InOut_Recipe,
		stHmiBridgeOld.stInOut.usiRecipeNo,
		stHmiBridgeCtrl.stInOut.usiRecipeNo);
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

void _INIT ProgramInit(void)
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

void _CYCLIC ProgramCyclic(void)
{
	HmiBridgeSyncRegisteredVariables();
	HmiBridgeDemoControlStep();
	HmiBridgeSyncRegisteredVariables();
}

void _EXIT ProgramExit(void)
{
}
