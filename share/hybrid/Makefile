#!/usr/bin/make -f

PROG = gpu-manager
OBJ = gpu-manager.o json-parser/json.o

override CFLAGS += -Wall $(shell pkg-config --cflags libpci libdrm libkmod)
override LDLIBS += $(shell pkg-config --libs libpci libdrm libkmod) -lm

all: $(PROG)

$(PROG): $(OBJ)

clean:
	rm -f $(PROG) $(OBJ)
