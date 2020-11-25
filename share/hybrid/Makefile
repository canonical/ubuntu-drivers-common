#!/usr/bin/make -f

PROGRAM = gpu-manager
PROGRAM_FILES = gpu-manager.c
CC = gcc
CFLAGS =-g -Wall $(shell pkg-config --cflags libpci libdrm libkmod) -Ijson-parser json-parser/json.c
LDFLAGS =$(shell pkg-config --libs libpci libdrm libkmod) -lm

all: build

gpu-manager: gpu-manager.o
	$(CC) $(CFLAGS) gpu-manager.o $(LDFLAGS) -o gpu-manager

gpu-manager.o:
	$(CC) $(CFLAGS) -c gpu-manager.c

build: gpu-manager
clean:
	@rm -f $(PROGRAM) $(PROGRAM).o json.o
