CC ?= clang
CFLAGS += -Wall -O2
LDFLAGS += -lm

TOOL_NAME = vock
TARGET_EXE = vock
TARGET_LIB = mode/kcov.so
LIB_SOURCE = mode/kcov.c

EXE_OBJS = vock.o

.PHONY: all
all: $(TARGET_EXE) $(TARGET_LIB)

$(TARGET_EXE): $(EXE_OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

$(TARGET_LIB): $(LIB_SOURCE)
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $<

.PHONY: clean
clean:
	rm -f $(TARGET_EXE) $(TARGET_LIB) $(EXE_OBJS)
