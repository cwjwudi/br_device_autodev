#include "Function.h"
#include <stdlib.h>
#include <string.h>

/* HEX ±àÂë */
void byte_to_hex_str(uint8_t byte, char* out) {
	const char hex_chars[] = "0123456789ABCDEF";
	out[0] = hex_chars[(byte >> 4) & 0x0F];
	out[1] = hex_chars[byte & 0x0F];
}

void bytes_to_hex_string(const uint8_t* input, size_t len, char* output) {
	for (size_t i = 0; i < len; ++i) {
		byte_to_hex_str(input[i], output + i * 2);
	}
	output[len * 2] = '\0';
}

/* BASE64 ±àÂë */
static const char base64_table[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

int uint8_to_base64_string(const uint8_t *input, int input_len, char *output) {
	int i = 0;
	int out_idx = 0;

	while (i < input_len - 2) {
		uint8_t b0 = input[i];
		uint8_t b1 = input[i+1];
		uint8_t b2 = input[i+2];

		output[out_idx++] = base64_table[b0 >> 2];
		output[out_idx++] = base64_table[((b0 & 0x03) << 4) | (b1 >> 4)];
		output[out_idx++] = base64_table[((b1 & 0x0F) << 2) | (b2 >> 6)];
		output[out_idx++] = base64_table[b2 & 0x3F];

		i += 3;
	}

	if (i < input_len) {
		uint8_t b0 = input[i];
		uint8_t b1 = input[i+1];

		output[out_idx++] = base64_table[b0 >> 2];
		output[out_idx++] = base64_table[((b0 & 0x03) << 4) | (b1 >> 4)];
		output[out_idx++] = '=';
		output[out_idx++] = '=';
	} else if (i == input_len - 1) {
		uint8_t b0 = input[i];

		output[out_idx++] = base64_table[b0 >> 2];
		output[out_idx++] = base64_table[(b0 & 0x03) << 4];
		output[out_idx++] = '=';
		output[out_idx++] = '=';
	}

	output[out_idx] = '\0';

	return out_idx;
}

INT find_min_of_three(INT val1, INT val2, INT val3) {
	INT min_val = val1;

	if (val2 < min_val) {
		min_val = val2;
	}
	if (val3 < min_val) {
		min_val = val3;
	}

	return min_val;
}

INT cal_BST_Idx(INT val1, INT val2, INT val3, USINT* out1, USINT* out2, USINT* out3) {
	INT min_val = val1;
	min_val = find_min_of_three(val1, val2, val3);
	INT offset = 0;
	if (min_val < 0) {
		offset = -min_val;
	}

	*out1 = (USINT)(val1 + offset);
	*out2 = (USINT)(val2 + offset);
	*out3 = (USINT)(val3 + offset);

	return offset;
}

UDINT cal_LatchPos(INT idx1, INT idx2, DINT diSImage, UDINT CurLatchPos) {
	INT minIdx = find_min_of_three(idx1, idx2, 0);

	DINT offset = (DINT)minIdx * (DINT)BST_SEG_UM;

	DINT tempPos = (DINT)CurLatchPos + offset;

	DINT maxLimit = (DINT)diSImage;

	if (tempPos < 0) {
		DINT cycles = (-tempPos) / (maxLimit + 1) + 1;
		tempPos += cycles * (maxLimit + 1);
	}

	tempPos = tempPos % (maxLimit + 1);

	if (tempPos < 0) {
		tempPos = 0;
	}
	return (UDINT)tempPos;
}

REAL random_real(REAL rMin, REAL rMax) {
	REAL lo = rMin;
	REAL hi = rMax;
	REAL t;

	if (hi < lo) {
		REAL tmp = lo;
		lo = hi;
		hi = tmp;
	}

	if (lo == hi) {
		return lo;
	}

	t = (REAL)rand() / ((REAL)RAND_MAX + 1.0f);
	return lo + t * (hi - lo);
}
