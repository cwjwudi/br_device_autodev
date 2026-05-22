
#include <bur/plctypes.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

#define SVG_MAX_PU_COUNT_LIMIT 8

#define SVG_TEMPLATE_TEXT "[{\"select\":\"#emergency\",\"duration\":0,\"style\":\"fill:1\"},{\"select\":\"#line_1\",\"duration\":0,\"style\":\"display:inline\"},{\"select\":\"#line_2\",\"duration\":0,\"style\":\"display:inline\"},{\"select\":\"#fan1\",\"duration\":   0,\"spin\":[0,0,0]  },{\"select\":\"#roller_up\",\"duration\":1000,\"translate\":[168, 425]},{\"select\":\"#roller_down\",\"duration\":0,\"style\":\"fill:2\"},{\"select\":\"#color_box\",\"duration\":0,\"style\":\"fill:3\"}]"

static void SvgInitField(SvgTransformField_typ* pField, UINT uiOffset, UINT uiLength)
{
	pField->uiOffset = uiOffset;
	pField->uiLength = uiLength;
}

static void SvgInitPuUnit(SvgPuUnit_typ* pPu)
{
	pPu->stCmd.bEmergency = 0;
	pPu->stCmd.bLine1Visible = 1;
	pPu->stCmd.bLine2Visible = 1;
	pPu->stCmd.bFan1Rotate = 0;
	pPu->stCmd.bRollerUpDown = 0;
	pPu->stCmd.bRollerDownGreen = 0;
	pPu->stCmd.bColorBoxYellow = 0;
	pPu->stCmd.bManualTestMode = 0;

	brsstrcpy((UDINT)pPu->stText.strTemplate, (UDINT)SVG_TEMPLATE_TEXT);
	brsstrcpy((UDINT)pPu->stText.strEmergencyNormal, (UDINT)"fill:1");
	brsstrcpy((UDINT)pPu->stText.strEmergencyAlarm, (UDINT)"fill:3");
	brsstrcpy((UDINT)pPu->stText.strDisplayShow, (UDINT)"display:inline");
	brsstrcpy((UDINT)pPu->stText.strDisplayHide, (UDINT)"display:none  ");
	brsstrcpy((UDINT)pPu->stText.strFan1DurationStop, (UDINT)"   0");
	brsstrcpy((UDINT)pPu->stText.strFan1DurationRun, (UDINT)"1000");
	brsstrcpy((UDINT)pPu->stText.strFan1SpinStop, (UDINT)"[0,0,0]  ");
	brsstrcpy((UDINT)pPu->stText.strFan1SpinRun, (UDINT)"[360,0,0]");
	brsstrcpy((UDINT)pPu->stText.strRollerUpHome, (UDINT)"[168, 425]");
	brsstrcpy((UDINT)pPu->stText.strRollerUpDown, (UDINT)"[168, 470]");
	brsstrcpy((UDINT)pPu->stText.strRollerDownNormal, (UDINT)"fill:2");
	brsstrcpy((UDINT)pPu->stText.strRollerDownGreen, (UDINT)"fill:1");
	brsstrcpy((UDINT)pPu->stText.strColorBoxNormal, (UDINT)"fill:3");
	brsstrcpy((UDINT)pPu->stText.strColorBoxYellow, (UDINT)"fill:0");

	SvgInitField(&pPu->stMap.stEmergencyStyle, 46, 6);
	SvgInitField(&pPu->stMap.stLine1Style, 97, 14);
	SvgInitField(&pPu->stMap.stLine2Style, 156, 14);
	SvgInitField(&pPu->stMap.stFan1Duration, 202, 4);
	SvgInitField(&pPu->stMap.stFan1Spin, 214, 9);
	SvgInitField(&pPu->stMap.stRollerUpTranslate, 276, 10);
	SvgInitField(&pPu->stMap.stRollerDownStyle, 335, 6);
	SvgInitField(&pPu->stMap.stColorBoxStyle, 389, 6);

	brsstrcpy((UDINT)pPu->strTransform, (UDINT)"");
	pPu->bTransformReady = 0;
}

void _INIT ProgramInit(void)
{
	USINT usiIdx;

	brsstrcpy((UDINT)strTransform, (UDINT)"");
	usiSvgPuCount = 1;
	usiActiveSvgPu = 0;

	for (usiIdx = 0; usiIdx < SVG_MAX_PU_COUNT_LIMIT; usiIdx++) {
		SvgInitPuUnit(&astSvgPu[usiIdx]);
	}
}
