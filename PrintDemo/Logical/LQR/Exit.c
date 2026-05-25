
#include <bur/plctypes.h>

#ifdef _DEFAULT_INCLUDES
	#include <AsDefault.h>
#endif

void _EXIT ProgramExit(void)
{
	arLqrU[0] = 0.0f;
	arLqrU[1] = 0.0f;
	stLqrStatus.bValid = 0;
}
