PRJ     ?= blink
FOLDER  ?= $(PRJ)

#BOARD   ?= esp32s3_devkitc/esp32s3/procpu
#OVERLAY ?= esp32s3_devkitc
BOARD   ?= native_sim
OVERLAY ?= native_sim

ORANGE  :=\033[38;5;214m
RESET   :=\033[0m

start:
	python scripts/zephyr_env.py -p $(PRJ) -o $(FOLDER) -b $(BOARD) -y $(OVERLAY)

add_driver:
	make -C $(PRJ) add-driver

build:
	make -C $(PRJ) west-build

run:
	make -C $(PRJ) west-run

clean: 
	make -C $(PRJ) clean

clean_all: 
	rm -rf $(PRJ) modules

help:
	@printf "\n$(ORANGE)Zephyr Project Generator\n\n"
	@printf "Usage:\n"
	@printf "  make start\n"
	@printf "  make build\n"
	@printf "  make run\n\n"
	@printf "This runs:\n"
	@printf "  python zephyr_env.py -p $(PRJ) -o $(FOLDER) -b $(BOARD) -y $(OVERLAY)\n\n"
	@printf "Options (from zephyr_env.py):\n"
	@printf "  -p, --project_name        Project name\n"
	@printf "  -v, --c_make_version      CMake minimum version (default: 3.20.0)\n"
	@printf "  -l, --languages           Languages used in project (default: C)\n"
	@printf "  -o, --output_folder       Output folder (default: current directory)\n"
	@printf "  -b, --board               Target board (default: qemu_riscv64)\n"
	@printf "  -y, --overlay             Overlay file name (default: app)\n"
	@printf "      --overwrite           Overwrite existing files\n\n"
	@printf "Makefile defaults (override on the command line):\n"
	@printf "  PRJ=%s\n" "$(PRJ)"
	@printf "  FOLDER=%s\n" "$(FOLDER)"
	@printf "  BOARD=%s\n" "$(BOARD)"
	@printf "  OVERLAY=%s\n" "$(OVERLAY)"
	@printf "$(RESET)\n"

