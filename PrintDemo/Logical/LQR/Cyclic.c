
#include <bur/plctypes.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

#define LQR_STATE_COUNT_C 4
#define LQR_INPUT_COUNT_C 2
#define LQR_GAIN_STRIDE_C 4

static REAL LqrAbs(REAL value)
{
	if (value < 0.0f) {
		return -value;
	}

	return value;
}

static REAL LqrClamp(REAL value, REAL limit)
{
	if (value > limit) {
		stLqrStatus.bSaturated = 1;
		return limit;
	}
	if (value < -limit) {
		stLqrStatus.bSaturated = 1;
		return -limit;
	}

	return value;
}

static void LqrClearOutput(void)
{
	USINT i;

	for (i = 0; i < LQR_INPUT_COUNT_C; i++) {
		arLqrU[i] = 0.0f;
	}
}

static void LqrClearError(void)
{
	USINT i;

	for (i = 0; i < LQR_STATE_COUNT_C; i++) {
		arLqrError[i] = 0.0f;
	}
}

void _CYCLIC ProgramCyclic(void)
{
	USINT i;
	USINT j;
	REAL rSum;
	REAL rLimit;

	stLqrStatus.bEnabled = bLqrEnable;
	stLqrStatus.bValid = 0;
	stLqrStatus.bSaturated = 0;
	stLqrStatus.usiErrorCode = 0;

	if (bLqrReset) {
		LqrClearOutput();
		LqrClearError();
		return;
	}

	if (!bLqrEnable) {
		LqrClearOutput();
		return;
	}

	rLimit = LqrAbs(rLqrMaxAbsU);
	if (rLimit <= 0.0f) {
		LqrClearOutput();
		stLqrStatus.usiErrorCode = 1;
		return;
	}

	for (i = 0; i < LQR_STATE_COUNT_C; i++) {
		arLqrError[i] = arLqrX[i] - arLqrXRef[i];
	}

	for (j = 0; j < LQR_INPUT_COUNT_C; j++) {
		rSum = 0.0f;
		for (i = 0; i < LQR_STATE_COUNT_C; i++) {
			rSum += arLqrK[(j * LQR_GAIN_STRIDE_C) + i] * arLqrError[i];
		}
		arLqrU[j] = LqrClamp(-rSum, rLimit);
	}

	stLqrStatus.bValid = 1;
	if (stLqrStatus.bSaturated) {
		stLqrStatus.usiErrorCode = 2;
	}
}
