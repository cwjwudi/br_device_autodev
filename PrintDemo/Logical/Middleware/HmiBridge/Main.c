
#include <bur/plctypes.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

#include "HmiBridgeSync.h"
#include "HmiBridgeControl.h"

void _INIT ProgramInit(void)
{
	HmiBridgeInitDemoValues();
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
