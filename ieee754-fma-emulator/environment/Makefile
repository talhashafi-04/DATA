CC := gcc
CFLAGS := -O2 -std=c11 -Wall -Wextra
LDLIBS := -lmpfr -lgmp

.PHONY: all clean

all: fma_runner

fma_runner: fma_runner.o softfma.o
	$(CC) $(CFLAGS) $^ $(LDLIBS) -o $@

fma_runner.o: fma_runner.c
	$(CC) $(CFLAGS) -c $< -o $@

softfma.o: softfma.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f fma_runner *.o
