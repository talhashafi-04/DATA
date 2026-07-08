#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

double softfma(double a, double b, double c);

typedef struct {
    char a[64];
    char b[64];
    char c[64];
    char expected[64];
} Case;

static char *read_file(const char *path) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return NULL;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    long size = ftell(file);
    if (size < 0) {
        fclose(file);
        return NULL;
    }
    rewind(file);
    char *buffer = calloc((size_t)size + 1u, 1u);
    if (buffer == NULL) {
        fclose(file);
        return NULL;
    }
    if (fread(buffer, 1u, (size_t)size, file) != (size_t)size) {
        free(buffer);
        fclose(file);
        return NULL;
    }
    fclose(file);
    return buffer;
}

static const char *extract_string(const char *object, const char *key, char *out, size_t out_size) {
    char pattern[32];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *cursor = strstr(object, pattern);
    if (cursor == NULL) {
        return NULL;
    }
    cursor = strchr(cursor + strlen(pattern), ':');
    if (cursor == NULL) {
        return NULL;
    }
    cursor++;
    while (*cursor != '\0' && isspace((unsigned char)*cursor)) {
        cursor++;
    }
    if (*cursor != '"') {
        return NULL;
    }
    cursor++;
    size_t length = 0;
    while (cursor[length] != '\0' && cursor[length] != '"') {
        length++;
    }
    if (cursor[length] != '"' || length + 1u > out_size) {
        return NULL;
    }
    memcpy(out, cursor, length);
    out[length] = '\0';
    return cursor + length + 1u;
}

static int parse_case(const char *object, Case *item) {
    return extract_string(object, "a", item->a, sizeof(item->a)) != NULL &&
           extract_string(object, "b", item->b, sizeof(item->b)) != NULL &&
           extract_string(object, "c", item->c, sizeof(item->c)) != NULL &&
           extract_string(object, "expected", item->expected, sizeof(item->expected)) != NULL;
}

static double parse_hex_float(const char *text) {
    errno = 0;
    char *end = NULL;
    double value = strtod(text, &end);
    if (end == text || errno == ERANGE) {
        return NAN;
    }
    return value;
}

static unsigned long long double_bits(double value) {
    unsigned long long bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static void format_double(double value, char *out, size_t out_size) {
    unsigned long long bits = double_bits(value);
    unsigned sign = (unsigned)(bits >> 63);
    unsigned exponent = (unsigned)((bits >> 52) & 0x7ffu);
    unsigned long long fraction = bits & 0x000fffffffffffffull;

    if (exponent == 0x7ffu) {
        if (fraction != 0) {
            snprintf(out, out_size, "nan");
        } else {
            snprintf(out, out_size, "%sinf", sign ? "-" : "");
        }
        return;
    }

    if (exponent == 0) {
        snprintf(out, out_size, "%s0x0.%013llxp-1022", sign ? "-" : "", fraction);
        if (fraction == 0) {
            snprintf(out, out_size, "%s0x0.0p+0", sign ? "-" : "");
        }
        return;
    }

    snprintf(out, out_size, "%s0x1.%013llxp%+d", sign ? "-" : "", fraction, (int)exponent - 1023);
}

static int same_hex(const char *expected, const char *actual) {
    if (strcmp(expected, "nan") == 0 && strcmp(actual, "nan") == 0) {
        return 1;
    }
    return strcmp(expected, actual) == 0;
}

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/app/data/cases.json";
    char *json = read_file(path);
    if (json == NULL) {
        fprintf(stderr, "could not read %s\n", path);
        return 2;
    }

    int failures = 0;
    int count = 0;
    const char *cursor = json;
    while ((cursor = strchr(cursor, '{')) != NULL) {
        const char *end = strchr(cursor, '}');
        if (end == NULL) {
            break;
        }
        Case item;
        memset(&item, 0, sizeof(item));
        if (!parse_case(cursor, &item)) {
            free(json);
            fprintf(stderr, "malformed case near index %d\n", count);
            return 2;
        }

        double a = parse_hex_float(item.a);
        double b = parse_hex_float(item.b);
        double c = parse_hex_float(item.c);
        double actual = softfma(a, b, c);
        char actual_hex[64];
        format_double(actual, actual_hex, sizeof(actual_hex));
        int passed = same_hex(item.expected, actual_hex);
        printf("%s,%s,%s %s %s %s\n",
               item.a, item.b, item.c, item.expected, actual_hex, passed ? "pass" : "fail");
        if (!passed) {
            failures++;
        }
        count++;
        cursor = end + 1;
    }

    free(json);
    if (count == 0) {
        fprintf(stderr, "no cases found in %s\n", path);
        return 2;
    }
    return failures == 0 ? 0 : 1;
}
