
#include <bur/plctypes.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

#define LQR_STATE_COUNT_C 4
#define LQR_INPUT_COUNT_C 2
#define LQR_GAIN_COUNT_C 8

static void LqrClearVectors(void)
{
	USINT i;

	for (i = 0; i < LQR_STATE_COUNT_C; i++) {
		arLqrX[i] = 0.0f;
		arLqrXRef[i] = 0.0f;
		arLqrError[i] = 0.0f;
	}

	for (i = 0; i < LQR_INPUT_COUNT_C; i++) {
		arLqrU[i] = 0.0f;
	}
}

static void LqrLoadDefaultGains(void)
{
	USINT i;

	for (i = 0; i < LQR_GAIN_COUNT_C; i++) {
		arLqrK[i] = 0.0f;
	}

	arLqrK[0] = 2.0f;
	arLqrK[1] = 0.4f;
	arLqrK[6] = 2.0f;
	arLqrK[7] = 0.4f;
}

void _INIT ProgramInit(void)
{
	bLqrEnable = 0;
	bLqrReset = 0;
	bLqrUseManualGains = 0;
	rLqrMaxAbsU = 100.0f;
	stLqrStatus.bEnabled = 0;
	stLqrStatus.bValid = 0;
	stLqrStatus.bSaturated = 0;
	stLqrStatus.usiErrorCode = 0;

	LqrClearVectors();
	LqrLoadDefaultGains();
}
