#ifndef HMIBRIDGE_SYNC_H
#define HMIBRIDGE_SYNC_H

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

static void HmiBridgeSyncRegisteredVariables(void)
{
#define HMI_INPUT(hmiVar, ctrlVar) HMI_TO_CTRL(hmiVar, ctrlVar);
#define HMI_OUTPUT(hmiVar, ctrlVar) CTRL_TO_HMI(hmiVar, ctrlVar);
#define HMI_INOUT(hmiVar, oldVar, ctrlVar) READ_WRITE(hmiVar, oldVar, ctrlVar);

#include "HmiBridgeRegistry.def"

#undef HMI_INPUT
#undef HMI_OUTPUT
#undef HMI_INOUT
}

#endif
