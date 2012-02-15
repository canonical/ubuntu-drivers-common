#!/usr/bin/make -f

PROGRAM = hybrid-detect
PROGRAM_FILES = hybrid-detect.c
CC = gcc
CFLAGS =-g -Wall $(shell pkg-config --cflags --libs pciaccess)

all: build

build:
	$(CC) -o $(PROGRAM) $(PROGRAM_FILES) $(CFLAGS)

clean:
	@rm -f $(PROGRAM)
