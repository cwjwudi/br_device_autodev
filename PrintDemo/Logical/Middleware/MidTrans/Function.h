#ifndef MIDTRANS_FUNCTION_H
#define MIDTRANS_FUNCTION_H

#include <bur/plctypes.h>
#include <stddef.h>

#define uint8_t USINT
#define BST_SEG_UM 20000U

void byte_to_hex_str(uint8_t byte, char* out);
void bytes_to_hex_string(const uint8_t* input, size_t len, char* output);
int uint8_to_base64_string(const uint8_t *input, int input_len, char *output);
INT find_min_of_three(INT val1, INT val2, INT val3);
INT cal_BST_Idx(INT val1, INT val2, INT val3, USINT* out1, USINT* out2, USINT* out3);
UDINT cal_LatchPos(INT idx1, INT idx2, DINT diSImage, UDINT CurLatchPos);
REAL random_real(REAL rMin, REAL rMax);

#endif
