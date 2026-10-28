CLANG   ?= clang
ARCH    := $(shell uname -m | sed 's/x86_64/x86/' | sed 's/aarch64/arm64/')
KERN    := $(shell uname -r)
BPF_INC := /usr/src/linux-headers-$(KERN)/tools/bpf/resolve_btfids/libbpf/include

all: xdp_monitor.bpf.o

xdp_monitor.bpf.o: xdp_monitor.bpf.c vmlinux.h
	$(CLANG) -O2 -g -target bpf \
		-D__TARGET_ARCH_$(ARCH) \
		-I. \
		-I$(BPF_INC) \
		-c xdp_monitor.bpf.c \
		-o xdp_monitor.bpf.o
	@echo "Compilation OK : xdp_monitor.bpf.o"

clean:
	rm -f xdp_monitor.bpf.o