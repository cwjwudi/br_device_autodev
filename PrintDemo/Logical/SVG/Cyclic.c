
#include <bur/plctypes.h>
#include <stdlib.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

#define SVG_MAX_PU_COUNT_LIMIT 8

static void SvgLoadTemplate(SvgPuUnit_typ* pPu)
{
	brsstrcpy((UDINT)pPu->strTransform, (UDINT)pPu->stText.strTemplate);
	pPu->bTransformReady = 1;
}

static void SvgCopyField(SvgPuUnit_typ* pPu, SvgTransformField_typ* pField, char* pValue)
{
	brsmemcpy((UDINT)&pPu->strTransform[pField->uiOffset], (UDINT)pValue, pField->uiLength);
}

static void SvgApplyCommands(SvgPuUnit_typ* pPu)
{
	if (pPu->stCmd.bEmergency) {
		SvgCopyField(pPu, &pPu->stMap.stEmergencyStyle, pPu->stText.strEmergencyAlarm);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stEmergencyStyle, pPu->stText.strEmergencyNormal);
	}

	if (!pPu->stCmd.bRollerUpDown) {
		SvgCopyField(pPu, &pPu->stMap.stLine1Duration, pPu->stText.strRollerUpDuration);
		SvgCopyField(pPu, &pPu->stMap.stLine1Style, pPu->stText.strDisplayShow);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stLine1Duration, pPu->stText.strRollerUpDuration);
		SvgCopyField(pPu, &pPu->stMap.stLine1Style, pPu->stText.strDisplayHide);
	}

	if (pPu->stCmd.bRollerUpDown) {
		SvgCopyField(pPu, &pPu->stMap.stLine2Duration, pPu->stText.strRollerUpDuration);
		SvgCopyField(pPu, &pPu->stMap.stLine2Style, pPu->stText.strDisplayShow);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stLine2Duration, pPu->stText.strRollerUpDuration);
		SvgCopyField(pPu, &pPu->stMap.stLine2Style, pPu->stText.strDisplayHide);
	}

	if (pPu->stCmd.bFan1Rotate) {
		SvgCopyField(pPu, &pPu->stMap.stFan1Duration, pPu->stText.strFan1DurationRun);
		SvgCopyField(pPu, &pPu->stMap.stFan1Spin, pPu->stText.strFan1SpinRun);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stFan1Duration, pPu->stText.strFan1DurationStop);
		SvgCopyField(pPu, &pPu->stMap.stFan1Spin, pPu->stText.strFan1SpinStop);
	}

	if (pPu->stCmd.bRollerUpDown) {
		SvgCopyField(pPu, &pPu->stMap.stRollerUpDuration, pPu->stText.strRollerUpDuration);
		SvgCopyField(pPu, &pPu->stMap.stRollerUpTranslate, pPu->stText.strRollerUpDown);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stRollerUpDuration, pPu->stText.strRollerUpDuration);
		SvgCopyField(pPu, &pPu->stMap.stRollerUpTranslate, pPu->stText.strRollerUpHome);
	}

	if (pPu->stCmd.bRollerDownGreen) {
		SvgCopyField(pPu, &pPu->stMap.stRollerDownStyle, pPu->stText.strRollerDownGreen);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stRollerDownStyle, pPu->stText.strRollerDownNormal);
	}

	if (pPu->stCmd.bColorBoxYellow) {
		SvgCopyField(pPu, &pPu->stMap.stColorBoxStyle, pPu->stText.strColorBoxYellow);
	} else {
		SvgCopyField(pPu, &pPu->stMap.stColorBoxStyle, pPu->stText.strColorBoxNormal);
	}
}

static USINT SvgGetValidPuCount(void)
{
	if (usiSvgPuCount == 0) {
		usiSvgPuCount = 1;
	}

	if (usiSvgPuCount > SVG_MAX_PU_COUNT_LIMIT) {
		usiSvgPuCount = SVG_MAX_PU_COUNT_LIMIT;
	}

	return usiSvgPuCount;
}

static USINT SvgGetActivePuIndex(USINT usiPuCount)
{
	if (usiActiveSvgPu >= usiPuCount) {
		usiActiveSvgPu = 0;
	}

	return usiActiveSvgPu;
}

static BOOL SvgRandomBool(void)
{
	return (BOOL)(rand() & 1);
}

static void SvgRandomizePu(SvgPuUnit_typ* pPu)
{
	pPu->stCmd.bManualTestMode = 0;
	pPu->stCmd.bEmergency = SvgRandomBool();
	pPu->stCmd.bFan1Rotate = SvgRandomBool();
	pPu->stCmd.bRollerUpDown = SvgRandomBool();
	pPu->stCmd.bRollerDownGreen = SvgRandomBool();
	pPu->stCmd.bColorBoxYellow = SvgRandomBool();
	pPu->bTransformReady = 0;
}

static void SvgRunRandomMotionOnce(USINT usiPuCount)
{
	USINT usiIdx;

	for (usiIdx = 0; usiIdx < usiPuCount; usiIdx++) {
		SvgRandomizePu(&astSvgPu[usiIdx]);
	}
}

void _CYCLIC ProgramCyclic(void)
{
	USINT usiIdx;
	USINT usiPuCount;
	USINT usiActiveIdx;

	usiPuCount = SvgGetValidPuCount();
	usiActiveIdx = SvgGetActivePuIndex(usiPuCount);

	if (bRandomMotionTestMode && bCmdRandomMotionOnce && !bOldCmdRandomMotionOnce) {
		SvgRunRandomMotionOnce(usiPuCount);
	}
	bOldCmdRandomMotionOnce = bCmdRandomMotionOnce;

	if (astSvgPu[usiActiveIdx].stCmd.bManualTestMode) {
		astSvgPu[usiActiveIdx].bTransformReady = 0;
		return;
	}

	for (usiIdx = 0; usiIdx < usiPuCount; usiIdx++) {
		if (!astSvgPu[usiIdx].bTransformReady) {
			SvgLoadTemplate(&astSvgPu[usiIdx]);
		}

		if (!astSvgPu[usiIdx].stCmd.bManualTestMode) {
			SvgApplyCommands(&astSvgPu[usiIdx]);
		}
	}

	brsstrcpy((UDINT)strTransform, (UDINT)astSvgPu[usiActiveIdx].strTransform);
}
