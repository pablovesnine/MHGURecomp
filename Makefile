# MHGU Recomp build
# Internal Linux ARM64 build rules. Use tools/build-linux-release.sh on the host.
#
#   make gen GAME=<folder with exefs/ and romfs/>   recompile the game code from your own dump into generated/
#   make -j2                                        build the ARM64 runtime and available game code library
# build/ holds only the game folder (what a player copies); the compiler's files go to obj/.
PLATFORM ?= linux
ifneq ($(PLATFORM),linux)
$(error Unsupported PLATFORM=$(PLATFORM); this fork builds Linux ARM64 only)
endif

GAME     ?= ../mhgu/game
GEN      ?= generated
B        ?= build
O        ?= obj
CC       := $(if $(filter default undefined,$(origin CC)),clang,$(CC))
CXX      := $(if $(filter default undefined,$(origin CXX)),clang++,$(CXX))
TEST_RUNNER ?=
JOBS ?= $(shell nproc)
include tools/desktop-arch.mk
GENFLAGS := -O1 -fno-strict-aliasing -ffp-contract=off -fno-math-errno -Wno-return-type -Wno-unused-label \
            -Wno-parentheses-equality -Wno-unused-value -fvisibility=hidden -Iruntime $(GENARCH)

GEN_SRC  := $(wildcard $(GEN)/main/*.c) $(wildcard $(GEN)/sdk/*.c)
GEN_OBJ  := $(patsubst $(GEN)/%.c,$(O)/gen/%.o,$(GEN_SRC)) $(O)/gen/tools/gamelib_entry.o
RT_SRC   := $(wildcard runtime/*.c) $(wildcard runtime/hle/*.c) $(wildcard runtime/services/*.c) $(wildcard runtime/net/*.c) \
            runtime/nvn/objects.c runtime/nvn/cmdbuf.c runtime/nvn/nvn_args.c runtime/nvn/tegra.c runtime/nvn/formats.c \
            runtime/nvn/backend_null.c runtime/nvn/astc.c runtime/nvn/bcn.c runtime/nvn/maxwell/translate.c $(wildcard runtime/nvn/vulkan/*.c) \
            runtime/platform/$(PLATFORM).c
# (simd_int.c / neon.c, helpers of the recompiled code, live in the executable: the game code library imports them,
# and runtime/interp.c uses them too)
RT_HDRS  := $(wildcard runtime/*.h) $(wildcard runtime/net/*.h) $(wildcard runtime/platform/*.h) $(wildcard runtime/nvn/*.h) $(wildcard runtime/nvn/*/*.h)

# FFmpeg (the game's movies, runtime/hle/movie.c): by default a small static build of a pinned FFmpeg release, made
# here from its source (downloaded once to third_party/ffmpeg/, checked against FFMPEG_SHA256) with only what the movies
# use: MP4 holding H.264 video and AAC audio. Nothing to install or ship (Linux distributions carry different FFmpeg
# versions, and an executable linked to one doesn't start with another), and no GPL parts: FFmpeg's LGPL 2.1 only.
# FFMPEG=system links the system's own avformat / avcodec / avutil instead.
FFMPEG        ?= bundled
FFMPEG_VER    := 9.0.2
FFMPEG_SHA256 := 8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
FFMPEG_TAR    := third_party/ffmpeg/ffmpeg-$(FFMPEG_VER).tar.xz
FFMPEG_DIR    := $(O)/ffmpeg-$(FFMPEG_VER)
FFMPEG_LIBS   := $(addprefix $(FFMPEG_DIR)/lib/,libavformat.a libavcodec.a libavutil.a)
FFMPEG_CONF   := --disable-everything --disable-programs --disable-doc --disable-network --disable-autodetect \
                 --disable-debug --disable-avdevice --disable-avfilter --disable-swscale --disable-swresample \
                 --enable-static --disable-shared --enable-protocol=file --enable-demuxer=mov \
                 --enable-parser=h264,aac --enable-decoder=h264,aac
FFMPEG_CONF   += $(FFMPEG_TARGET_FLAGS)
FFMPEG_CC      = $(CC) $(TARGET_FLAGS)
ifeq ($(FFMPEG),system)
AV_LIBS  := -lavformat -lavcodec -lavutil
AV_DEPS  :=
else
AV_DEPS  := $(FFMPEG_LIBS)
AV_LIBS  :=
endif

# SDL3 and shaderc (Linux): by default static builds of pinned releases, made here from their sources like FFmpeg
# (downloaded once to third_party/, checked against their SHA-256). Not
# every distribution has them (Ubuntu 24.04 / Linux Mint 22: no SDL3), and a distribution's own can need a newer glibc
# than GLIBC_MAX. SDL still loads X11, Wayland, libdecor, PipeWire / PulseAudio / ALSA, udev... from the system when
# it runs, as its shared library does. Needs cmake. SDL3=system / SHADERC=system link the system's libSDL3.so.0 /
# libshaderc_shared.so.1 instead.
SDL3          ?= bundled
SHADERC       ?= bundled
SDL3_VER      := 3.4.18
SDL3_SHA256   := 9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3
SDL3_TAR      := third_party/sdl3/SDL3-$(SDL3_VER).tar.gz
SDL3_DIR      := $(O)/sdl3-$(SDL3_VER)
SDL3_CONF     := -DSDL_SHARED=OFF -DSDL_STATIC=ON -DSDL_TEST_LIBRARY=OFF -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF
# (what a player's desktop needs: the configure must find these, or SDL would quietly build without them)
SDL3_NEED     := X11 WAYLAND WAYLAND_LIBDECOR PIPEWIRE PULSEAUDIO ALSA HIDAPI LIBUDEV DBUS
# shaderc with the glslang and SPIRV-Tools / SPIRV-Headers releases it was released with, in one static library
SHADERC_VER   := 2026.4
GLSLANG_VER   := 16.6.0
SPIRV_VER     := 1.4.363.0
SHADERC_PARTS := shaderc-$(SHADERC_VER) glslang-$(GLSLANG_VER) SPIRV-Tools-$(SPIRV_VER) SPIRV-Headers-$(SPIRV_VER)
SHADERC_TARS  := $(patsubst %,third_party/shaderc/%.tar.gz,$(SHADERC_PARTS))
SHADERC_DIR   := $(O)/shaderc-$(SHADERC_VER)
SHADERC_CONF  := -DSHADERC_SKIP_TESTS=ON -DSHADERC_SKIP_EXAMPLES=ON -DSHADERC_SKIP_COPYRIGHT_CHECK=ON \
                 -DSPIRV_SKIP_EXECUTABLES=ON -DSPIRV_SKIP_TESTS=ON -DSPIRV_WERROR=OFF -DSPIRV_TOOLS_BUILD_STATIC=ON \
                 -DENABLE_GLSLANG_BINARIES=OFF -DGLSLANG_TESTS=OFF
# (MAKEFLAGS=: cmake's own make runs on its own, not in this one's jobs)
CMAKE_BUILD   = cd $(1) && MAKEFLAGS= cmake -S src -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=$(CC) \
                    -DCMAKE_CXX_COMPILER=$(CXX) $(CMAKE_TARGET_FLAGS) -DCMAKE_POSITION_INDEPENDENT_CODE=ON $(2) > configure.log 2>&1 \
                    || { tail -20 configure.log; exit 1; }; \
                MAKEFLAGS= cmake --build build --parallel $(JOBS) $(3) > build.log 2>&1 || { tail -30 build.log; exit 1; }
ifeq ($(SDL3),system)
SDL_DEPS :=
SDL_LIBS := -lSDL3
else
SDL_DEPS := $(SDL3_DIR)/lib/libSDL3.a
SDL_LIBS := $(SDL_DEPS) -pthread -lm
endif
ifeq ($(SHADERC),system)
SHADERC_DEPS :=
SHADERC_LIBS := -lshaderc_shared
else
SHADERC_DEPS := $(SHADERC_DIR)/lib/libshaderc_combined.a
SHADERC_LIBS := $(SHADERC_DEPS)
endif
# Room packets use zstd. Build the pinned portable C library for the same
# target/sysroot as the runtime; never pick up an amd64 host archive.
ZSTD          ?= bundled
ZSTD_VER      := 1.5.7
ZSTD_SHA256   := eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3
ZSTD_TAR      := third_party/zstd/zstd-$(ZSTD_VER).tar.gz
ZSTD_DIR      := $(O)/zstd-$(ZSTD_VER)
ZSTD_FLAGS    := -O2 -fPIC -fsigned-char -DZSTD_DISABLE_ASM -DZSTD_LEGACY_SUPPORT=0 -DZSTD_NO_TRACE -DXXH_NAMESPACE=ZSTD_
ZSTD_AR       ?= llvm-ar
ifeq ($(ZSTD),system)
ZSTD_DEPS :=
ZSTD_LIBS := -lzstd
else
ZSTD_DEPS := $(ZSTD_DIR)/lib/libzstd.a
ZSTD_LIBS := $(ZSTD_DEPS)
endif
# the libraries' headers, for everything compiled here (the stamps: built before anything includes them)
LIB_INC    := $(if $(SDL_DEPS),-I$(SDL3_DIR)/include -DMHGU_SDL_BUNDLED) $(if $(SHADERC_DEPS),-I$(SHADERC_DIR)/include) \
              $(if $(ZSTD_DEPS),-I$(ZSTD_DIR)/include)
LIB_STAMPS := $(if $(SDL_DEPS),$(SDL3_DIR)/.built) $(if $(SHADERC_DEPS),$(SHADERC_DIR)/.built) $(if $(ZSTD_DEPS),$(ZSTD_DIR)/.built)

EXE      := $(B)/mhgurecomp
OSFLAGS  := -fsigned-char
GENFLAGS += -fPIC -fsigned-char
RT_SRC   += runtime/platform/linux_glibc.c $(if $(SDL_DEPS),runtime/platform/linux_sdl.c)
FFMPEG_CONF += --enable-pic
# (--exclude-libs: the static libraries linked in - SDL3, shaderc with glslang, FFmpeg - stay inside; only the runtime's
# own functions are exported, for the game code library. A Vulkan layer or overlay with its own glslang or SDL then
# doesn't bind to ours, as happened with ImGui: see IMGUIFLAGS.)
LDFLAGS  := -fuse-ld=lld -rdynamic -Wl,--exclude-libs,ALL $(SDL_LIBS) $(AV_LIBS) -lvulkan $(SHADERC_LIBS) $(ZSTD_LIBS) -lz -lpthread -ldl -lm
# The programs start with glibc GLIBC_MAX or later (Ubuntu 24.04, Linux Mint 22, Debian 13, SteamOS): calls to the
# functions newer glibc versions gave a new symbol version go to the old one (runtime/platform/linux_glibc.c), and the
# link checks that nothing newer is left.
GLIBC_MAX  := 2.39
GLIBC_WRAP := sqrtf acosf asinf atan2f log10f sinh cosh
GLIBC_WRAP_FLAGS := $(foreach f,$(GLIBC_WRAP),-Wl,--wrap=$(f))
LDFLAGS  += $(GLIBC_WRAP_FLAGS)
GAMELIB  := $(B)/mhgugame.so
GAMELIB_LDFLAGS := -shared -fuse-ld=lld

# GAMELIB_ID: what the game code library is compiled against. A library with another id is refused at startup.
GAMELIB_SRCS := tools/gen.py tools/lifter.py tools/neon.py tools/nso.py tools/gamelib_entry.c \
                runtime/hle/hle_symbols.txt runtime/cpu.h runtime/vfp.h runtime/neon_rt.h runtime/gamelib.h
GAMELIB_ID := $(shell (cat $(GAMELIB_SRCS); echo '$(GENFLAGS)') | sha256sum | cut -c1-16)
# Generated C must come from the current generator, not just link against a
# current ABI ID. Normalize CRLF like upstream so the source stamp is portable.
GEN_SRCS := tools/gen.py tools/lifter.py tools/neon.py tools/nso.py runtime/hle/hle_symbols.txt
GEN_ID = $(shell cat $(GEN_SRCS) | tr -d '\r' | sha256sum | cut -c1-16)
# SHADER_ID: the shader translator, whose output cache/programs.bin keeps (runtime/nvn/vulkan/exec.c): the cache stays
# valid across builds until the translator changes. (Line endings ignored: the same sources hash the same everywhere.)
SHADER_SRCS := runtime/nvn/maxwell/translate.c runtime/nvn/maxwell/shader.h
SHADER_ID := $(shell cat $(SHADER_SRCS) | tr -d '\r' | sha256sum | cut -c1-16)
# The supported release wrapper supplies the verified numeric upstream VERSION
# for the runtime log and post-make metadata. The fallback is for direct local
# development only; it does not establish release provenance.
VERSION ?= $(shell git describe --tags 2>/dev/null || echo unknown)

RT_OBJ   = $(patsubst runtime/%.c,$(O)/rt/%.o,$(RT_SRC)) $(RYUSRV_OBJ) $(RT_CXX) $(O)/rt/overlay.o $(O)/rt/settings_panel.o $(IMGUI_OBJ) \
           $(O)/updater/sha256.o $(ENET_OBJ)
RYUSRV_OBJ := $(patsubst runtime/net/ryusrv/%.cpp,$(O)/rt/net/ryusrv/%.o,$(wildcard runtime/net/ryusrv/*.cpp))
RYUSRVFLAGS := -std=c++20 -O2 -g -Wall -fsigned-char -Iruntime/net/ryusrv/shim -Iruntime/net/ryusrv
$(O)/rt/net/ryusrv/%.o: runtime/net/ryusrv/%.cpp $(wildcard runtime/net/ryusrv/*.h runtime/net/ryusrv/shim/*/*.h) runtime/net/ryusrv.h
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) $(RYUSRVFLAGS) -c $< -o $@
# The old source pin has no rooms. Once room.c exists, every ENet input is
# mandatory: a missing source must not silently produce a partial library.
ENET      := third_party/enet
ifneq ($(wildcard runtime/net/room.c),)
ENET_SRC  := $(addprefix $(ENET)/,callbacks.c compress.c host.c list.c packet.c peer.c protocol.c unix.c)
endif
ENET_OBJ  := $(patsubst $(ENET)/%.c,$(O)/enet/%.o,$(ENET_SRC))
ENETFLAGS := -O2 -g -w -fsigned-char -I$(ENET)/include -DHAS_FCNTL -DHAS_POLL -DHAS_GETADDRINFO -DHAS_GETNAMEINFO -DHAS_INET_PTON -DHAS_INET_NTOP -DHAS_MSGHDR_FLAGS -DHAS_SOCKLEN_T
$(O)/enet/%.o: $(ENET)/%.c $(wildcard $(ENET)/include/enet/*.h)
	@mkdir -p $(dir $@)
	$(CC) $(TARGET_FLAGS) $(ENETFLAGS) -c $< -o $@
# (updater/sha256.c: runtime/net/ldn.c hashes the matchmaking key with it)
# Dear ImGui with cimgui's C API (third_party/cimgui: Forge plugins' ImGui, runtime/forge_imgui.c, overlay.cpp)
IMGUI    := third_party/cimgui
IMGUI_SRC := $(IMGUI)/cimgui.cpp $(addprefix $(IMGUI)/imgui/,imgui.cpp imgui_draw.cpp imgui_tables.cpp imgui_widgets.cpp imgui_demo.cpp)
IMGUI_SRC += $(if $(filter 1,$(NULL_GPU)),,$(IMGUI)/imgui/backends/imgui_impl_vulkan.cpp)
IMGUI_OBJ := $(patsubst $(IMGUI)/%.cpp,$(O)/imgui/%.o,$(IMGUI_SRC))
# (-fvisibility=hidden: without it the executable exports Dear ImGui's C++ symbols, and an overlay that links the
# system ImGui (MangoHud -> libimgui.so.1) binds its HUD's calls into ours: its 1.91 ImFontAtlas handed to our 1.92
# code crashes at swap-chain creation. Our own code and the Forge plugins' ImGui thunks bind inside the executable.)
IMGUIFLAGS := -O2 -g -fvisibility=hidden -DCIMGUI_NO_EXPORT -I$(IMGUI) -I$(IMGUI)/imgui $(OSFLAGS) $(LIB_INC)
# VulkanMemoryAllocator is vendored for the isolated tools build.
RTFLAGS  := -O2 -g -fno-strict-aliasing -Wall -Wno-unused-function -Iruntime -Ithird_party/vk_mem_alloc -I$(IMGUI) -I$(ENET)/include $(OSFLAGS) $(LIB_INC)
# FSR 3.1 temporal upscaler (runtime/nvn/vulkan/fsr.c): third_party/fsr-vulkan = AMD FidelityFX SDK 1.1.4's FSR 3.1.4
# upscaler (host scheduler, Vulkan backend, its GLSL) + a portable C wrapper, all MIT. No AMD binaries: the shaders are
# compiled with shaderc from the embedded GLSL when first used (src/ffx_fsr3_shaderblobs.cpp), linked into the executable.
FSR      := third_party/fsr-vulkan
FFX      := $(FSR)/upstream/ffx-1.1.4/sdk
FSR_SRC  := $(FSR)/src/ffx_vk_portable.c $(FSR)/src/ffx_vk_fsr3_portable.cpp $(FSR)/src/ffx_fsr3_shaderblobs.cpp \
            $(FSR)/src/ffx_fsr3_glsl.c \
            $(addprefix $(FFX)/src/,shared/ffx_assert.cpp shared/ffx_message.cpp shared/ffx_object_management.cpp \
              shared/ffx_breadcrumbs_list.cpp components/fsr3upscaler/ffx_fsr3upscaler.cpp backends/vk/ffx_vk.cpp \
              backends/shared/ffx_shader_blobs.cpp)
FSR_OBJ  := $(patsubst $(FSR)/%,$(O)/fsr/%.o,$(FSR_SRC))
FSRFLAGS := -O2 -w -DFFX_VK_PORTABLE_HAS_FSR3_UPSCALER=1 -DFFX_FSR3UPSCALER=1 -DDISABLE_FFX_DEBUG_BREAK=1 $(OSFLAGS) $(LIB_INC) \
            -I$(FSR)/include -I$(FFX)/include -I$(FFX)/src/shared -I$(FFX)/src/components -I$(FFX)/src/backends/shared \
            -I$(FFX)/src/backends/shared/blob_accessors
# the GLSL embedded by ffx_fsr3_glsl.c (assembler .incbin, paths relative to the directory make runs in)
FFX_GPU  := $(FFX)/include/FidelityFX/gpu
FFX_PASS := $(FFX)/src/backends/vk/shaders/fsr3upscaler
$(O)/fsr/src/ffx_fsr3_glsl.c.o: FSRFLAGS += -DFFX_GPU_DIR='"$(FFX_GPU)"' -DFFX_PASS_DIR='"$(FFX_PASS)"'
$(O)/fsr/src/ffx_fsr3_glsl.c.o: $(wildcard $(FFX_GPU)/*.h $(FFX_GPU)/*/*.h $(FFX_PASS)/*.glsl)
RTFLAGS  += -I$(FSR)/include
.DEFAULT_GOAL := all
# NULL_GPU=1: no renderer (runtime/nvn/backend_null.c: the game runs, nothing is drawn)
ifeq ($(NULL_GPU),1)
RTFLAGS  += -DMHGU_NULL_BACKEND
RT_SRC   := $(filter-out runtime/nvn/vulkan/%,$(RT_SRC))
RT_CXX   :=
else
RT_CXX   := $(O)/rt/nvn/vulkan/vma.o $(FSR_OBJ)
endif

all: $(EXE) $(if $(GEN_SRC),$(GAMELIB)) licenses pipelist

# INI/settings regression test: no game dump or generated code required.
.PHONY: test-interp
test-interp:
	mkdir -p $(O)/interp-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld -std=gnu11 -O1 -fsigned-char -fno-strict-aliasing -ffp-contract=off -Iruntime tests/test_interp.c runtime/interp.c runtime/neon.c runtime/simd_int.c -lm -pthread -o $(O)/interp-test/test-interp
	timeout 120 $(TEST_RUNNER) $(O)/interp-test/test-interp

.PHONY: test-villagehub
test-villagehub:
	mkdir -p $(O)/villagehub-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld -std=gnu11 -O1 -fsigned-char -fno-strict-aliasing -Iruntime -ffunction-sections -fdata-sections -Wl,--gc-sections tests/test_villagehub.c -o $(O)/villagehub-test/test-villagehub
	$(TEST_RUNNER) $(O)/villagehub-test/test-villagehub

# Build before entering the offline container; no SDL/GPU/game data needed.
CROSSPLAY := $(O)/crossplay-test
CROSSPLAY_FLAGS := -std=gnu11 -O1 -g -Wall -Wno-unused-function -fsigned-char -fno-strict-aliasing -Iruntime -I$(ENET)/include $(if $(ZSTD_DEPS),-I$(ZSTD_DIR)/include) -pthread
CROSSPLAY_INIT := $(CROSSPLAY)/fixture.o
.PHONY: test-crossplay-bins test-crossplay
test-crossplay-bins: $(addprefix $(CROSSPLAY)/,test-room test-ryuldn test-xbridge emu-room ryusrv-main)
test-crossplay: test-crossplay-bins
	$(PY) tools/test-crossplay.py --bins "$(abspath $(CROSSPLAY))" --runner "$(TEST_RUNNER)"

$(CROSSPLAY_INIT): tests/crossplay_fixture.c
	@mkdir -p $(dir $@)
	$(CC) $(TARGET_FLAGS) -O1 -fsigned-char -c $< -o $@

$(CROSSPLAY)/test-room: tests/test_room.c runtime/net/room.c runtime/net/roomsrv.c $(ENET_OBJ) $(ZSTD_DEPS) $(CROSSPLAY_INIT)
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(CROSSPLAY_FLAGS) $(filter %.c %.o,$^) $(ZSTD_LIBS) -o $@
$(CROSSPLAY)/test-ryuldn: tests/test_ryuldn.c runtime/net/ryuldn.c $(CROSSPLAY_INIT)
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(CROSSPLAY_FLAGS) $^ -o $@
$(CROSSPLAY)/test-xbridge: tests/test_xbridge.c runtime/net/xbridge.c runtime/net/ryuldn.c runtime/net/room.c $(ENET_OBJ) $(ZSTD_DEPS) $(CROSSPLAY_INIT)
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(CROSSPLAY_FLAGS) $(filter %.c %.o,$^) $(ZSTD_LIBS) -o $@
$(CROSSPLAY)/emu-room: tests/emu_room.c runtime/net/room.c $(ENET_OBJ) $(ZSTD_DEPS) $(CROSSPLAY_INIT)
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(CROSSPLAY_FLAGS) $(filter %.c %.o,$^) $(ZSTD_LIBS) -o $@
$(CROSSPLAY)/ryusrv-main: tests/ryusrv_main.cpp $(RYUSRV_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) -fuse-ld=lld $(RYUSRVFLAGS) $^ -pthread -o $@

.PHONY: test-settings
test-settings: $(LIB_STAMPS)
	@mkdir -p $(O)/settings-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(RTFLAGS) tests/test_settings.c runtime/config.c runtime/config_store.c $(SDL_LIBS) -lm -o $(O)/settings-test/test-settings
	$(TEST_RUNNER) $(O)/settings-test/test-settings $(O)/settings-test/settings.ini

$(O)/gen/%.o: $(GEN)/%.c runtime/cpu.h runtime/vfp.h runtime/neon_rt.h
	@mkdir -p $(dir $@)
	@$(CC) $(TARGET_FLAGS) $(GENFLAGS) -c $< -o $@


# the id as a file, rewritten only when it changes: both sides of the library interface rebuild together
$(O)/gamelib.id: FORCE
	@mkdir -p $(O); [ "$$(cat $@ 2>/dev/null)" = '$(GAMELIB_ID)' ] || echo '$(GAMELIB_ID)' > $@

$(O)/gen/tools/gamelib_entry.o: tools/gamelib_entry.c $(O)/gamelib.id
	@mkdir -p $(dir $@)
	$(CC) $(TARGET_FLAGS) $(GENFLAGS) -DGAMELIB_ID='"$(GAMELIB_ID)"' -c $< -o $@
$(O)/rt/gamelib.o: $(O)/gamelib.id
$(O)/rt/gamelib.o: RTFLAGS += -DGAMELIB_ID='"$(GAMELIB_ID)"'
$(O)/shader.id: FORCE
	@mkdir -p $(O); [ "$$(cat $@ 2>/dev/null)" = '$(SHADER_ID)' ] || echo '$(SHADER_ID)' > $@
$(O)/rt/nvn/vulkan/exec.o: $(O)/shader.id
$(O)/rt/nvn/vulkan/exec.o: RTFLAGS += -DSHADER_ID='"$(SHADER_ID)"'
$(O)/version.id: FORCE
	@mkdir -p $(O); [ "$$(cat $@ 2>/dev/null)" = '$(VERSION)' ] || echo '$(VERSION)' > $@
$(O)/rt/ui.o: extras/icon/mhgurecomp-128.png
$(O)/rt/main.o: $(O)/version.id
$(O)/rt/main.o: RTFLAGS += -DMHGU_VERSION='"$(VERSION)"'

$(O)/rt/%.o: runtime/%.c $(RT_HDRS)
	@mkdir -p $(dir $@)
	$(CC) $(TARGET_FLAGS) $(RTFLAGS) -c $< -o $@

$(O)/rt/forge_imgui.o: runtime/forge_imgui_thunks.inc $(IMGUI)/cimgui.h
$(O)/rt/forge_imgui.o: RTFLAGS += -DCIMGUI_NO_EXPORT -Wno-unused-variable

$(O)/rt/overlay.o: runtime/overlay.cpp runtime/overlay.h runtime/forge.h
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) $(IMGUIFLAGS) $(if $(filter 1,$(NULL_GPU)),-DMHGU_NULL_BACKEND) -Wall -Iruntime -c $< -o $@

$(O)/rt/settings_panel.o: runtime/settings_panel.cpp runtime/settings_panel.h runtime/modorder.h runtime/config.h runtime/settings_locale.h runtime/settings_icons.h runtime/app_actions.h runtime/overlay.h runtime/net/net.h
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) $(IMGUIFLAGS) -Wall -Iruntime -c $< -o $@

$(O)/imgui/%.o: $(IMGUI)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) $(IMGUIFLAGS) -w -c $< -o $@

$(O)/rt/nvn/vulkan/vma.o: runtime/nvn/vulkan/vma.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) -O2 -w -Ithird_party/vk_mem_alloc -c $< -o $@

$(O)/fsr/%.c.o: $(FSR)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(TARGET_FLAGS) -std=c11 $(FSRFLAGS) -c $< -o $@

$(O)/fsr/%.cpp.o: $(FSR)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) -std=c++17 $(FSRFLAGS) -include $(FSR)/src/ffx_1_1_4_portability.hpp -c $< -o $@

$(EXE): $(RT_OBJ) $(AV_DEPS) $(ZSTD_DEPS)
	@mkdir -p $(dir $@)
	$(CXX) $(TARGET_FLAGS) -o $@ $^ $(LDFLAGS)
	$(GLIBC_CHECK)

# Shared SHA256 remains required by runtime/net/ldn.c; no updater executable.
$(O)/updater/sha256.o: updater/sha256.c updater/updater.h
	@mkdir -p $(dir $@)
	$(CC) $(TARGET_FLAGS) -O2 -g -Wall -c $< -o $@
# SDL3 / shaderc headers must exist before the runtime is compiled.
$(filter-out $(RYUSRV_OBJ) $(ENET_OBJ),$(RT_OBJ)): $(LIB_STAMPS)

# (Linux: a program starts with glibc GLIBC_MAX and libstdc++ GLIBCXX_MAX or later, see LDFLAGS; this checks the one
# just linked. GLIBCXX_MAX: GCC 13's, the oldest of those distributions.)
GLIBCXX_MAX := 3.4.32
ifeq ($(PLATFORM),linux)
define GLIBC_CHECK
@new=$$($(OBJDUMP) -T $@ | awk -v max=$(GLIBC_MAX) -v cxx=$(GLIBCXX_MAX) ' \
	  match($$0, /GLIBC_[0-9.]+/) { split(substr($$0, RSTART + 6, RLENGTH - 6), v, "."); split(max, m, "."); \
	    if (v[1] * 1000 + v[2] > m[1] * 1000 + m[2]) print "  " $$NF " (glibc " v[1] "." v[2] ")" } \
	  match($$0, /GLIBCXX_[0-9.]+/) { split(substr($$0, RSTART + 8, RLENGTH - 8), v, "."); split(cxx, m, "."); \
	    if (v[3] > m[3]) print "  " $$NF " (libstdc++ GLIBCXX_" v[1] "." v[2] "." v[3] ")" }'); \
	if [ -n "$$new" ]; then printf '%s needs a newer glibc / libstdc++ than $(GLIBC_MAX) / $(GLIBCXX_MAX) for:\n%s\n%s\n' \
	  $@ "$$new" "(glibc: add them to GLIBC_WRAP and runtime/platform/linux_glibc.c)"; rm -f $@; exit 1; fi
endef
endif

# the bundled libraries' sources (see FFMPEG, SDL3 and SHADERC above): downloaded once, checked against their SHA-256
# FETCH(file, url, sha256, optional checksum-equivalent mirror)
define FETCH
$(1):
	@mkdir -p $$(dir $$@)
	bash tools/fetch-verified.sh "$$@" "$(3)" "$(2)" $(4)
endef
$(eval $(call FETCH,$(FFMPEG_TAR),https://ffmpeg.org/releases/ffmpeg-$(FFMPEG_VER).tar.xz,$(FFMPEG_SHA256),https://distfiles.macports.org/ffmpeg/ffmpeg-$(FFMPEG_VER).tar.xz))
$(eval $(call FETCH,$(ZSTD_TAR),https://github.com/facebook/zstd/releases/download/v$(ZSTD_VER)/zstd-$(ZSTD_VER).tar.gz,$(ZSTD_SHA256),https://api.github.com/repos/meta/zstd/releases/assets/230758919))
$(eval $(call FETCH,$(SDL3_TAR),https://github.com/libsdl-org/SDL/releases/download/release-$(SDL3_VER)/SDL3-$(SDL3_VER).tar.gz,$(SDL3_SHA256)))
$(eval $(call FETCH,third_party/shaderc/shaderc-$(SHADERC_VER).tar.gz,https://github.com/google/shaderc/archive/refs/tags/v$(SHADERC_VER).tar.gz,f06ce5bcca94e5df7f34e115743597d0ad2e13c5fe9213c67dc8c76031241947))
$(eval $(call FETCH,third_party/shaderc/glslang-$(GLSLANG_VER).tar.gz,https://github.com/KhronosGroup/glslang/archive/refs/tags/$(GLSLANG_VER).tar.gz,9c09b901149c729df745057dafa815278aaa101b84d2b6e14f16a42de52f97f2))
$(eval $(call FETCH,third_party/shaderc/SPIRV-Tools-$(SPIRV_VER).tar.gz,https://github.com/KhronosGroup/SPIRV-Tools/archive/refs/tags/vulkan-sdk-$(SPIRV_VER).tar.gz,e6c83a215538fbfd265ccf398d3877985055df1273dbed73912bd05307664688))
$(eval $(call FETCH,third_party/shaderc/SPIRV-Headers-$(SPIRV_VER).tar.gz,https://github.com/KhronosGroup/SPIRV-Headers/archive/refs/tags/vulkan-sdk-$(SPIRV_VER).tar.gz,5b3a0d099f5c7649e29c0938476c462e71d66ad89a0bde42fa1ba3eb476956c9))

# the bundled FFmpeg: configure, build into $(FFMPEG_DIR)
$(FFMPEG_DIR)/.built: $(FFMPEG_TAR)
	rm -rf $(FFMPEG_DIR) && mkdir -p $(FFMPEG_DIR)/src
	tar -xJf $< -C $(FFMPEG_DIR)/src --strip-components=1
	cd $(FFMPEG_DIR)/src && ./configure --prefix="$(abspath $(FFMPEG_DIR))" --cc="$(FFMPEG_CC)" $(FFMPEG_CONF) > ../configure.log \
	    || { tail -20 ../configure.log; exit 1; }
	$(MAKE) -j$(JOBS) -C $(FFMPEG_DIR)/src install > $(FFMPEG_DIR)/build.log || { tail -30 $(FFMPEG_DIR)/build.log; exit 1; }
	touch $@
	@echo "ffmpeg: FFmpeg $(FFMPEG_VER) (H.264 + AAC in MP4) built in $(FFMPEG_DIR)"

$(FFMPEG_LIBS): $(FFMPEG_DIR)/.built ;

$(ZSTD_DIR)/.built: $(ZSTD_TAR)
	rm -rf $(ZSTD_DIR) && mkdir -p $(ZSTD_DIR)/src $(ZSTD_DIR)/obj $(ZSTD_DIR)/lib $(ZSTD_DIR)/include
	tar -xzf $< -C $(ZSTD_DIR)/src --strip-components=1 zstd-$(ZSTD_VER)/lib zstd-$(ZSTD_VER)/LICENSE
	@cd $(ZSTD_DIR) && for f in src/lib/common/*.c src/lib/compress/*.c src/lib/decompress/*.c; do \
	    $(CC) $(TARGET_FLAGS) $(ZSTD_FLAGS) -c $$f -o obj/$$(basename $$f .c).o || exit 1; done
	$(ZSTD_AR) rcs $(ZSTD_DIR)/lib/libzstd.a $(ZSTD_DIR)/obj/*.o
	cp $(ZSTD_DIR)/src/lib/zstd.h $(ZSTD_DIR)/src/lib/zstd_errors.h $(ZSTD_DIR)/include/
	touch $@
	@echo "zstd: zstd $(ZSTD_VER) built in $(ZSTD_DIR)"

$(ZSTD_DIR)/lib/libzstd.a: $(ZSTD_DIR)/.built ;

# the bundled SDL3: configure (checking that it found SDL3_NEED), build, install into $(SDL3_DIR)
$(SDL3_DIR)/.built: $(SDL3_TAR)
	rm -rf $(SDL3_DIR) && mkdir -p $(SDL3_DIR)/src
	tar -xzf $< -C $(SDL3_DIR)/src --strip-components=1
	$(call CMAKE_BUILD,$(SDL3_DIR),-DCMAKE_INSTALL_PREFIX="$(abspath $(SDL3_DIR))" $(SDL3_CONF),--target install)
	@cd $(SDL3_DIR) && for n in $(SDL3_NEED); do grep -Eq "^-- +SDL_$${n} +\(Wanted: ON\): ON$$" configure.log || \
	    { echo "sdl3: SDL $(SDL3_VER) was configured without SDL_$$n: install its development files (README.md, Linux)"; exit 1; }; done
	touch $@
	@echo "sdl3: SDL $(SDL3_VER) built in $(SDL3_DIR)"

$(SDL3_DIR)/lib/libSDL3.a: $(SDL3_DIR)/.built ;

# the bundled shaderc: its release with glslang, SPIRV-Tools and SPIRV-Headers in its third_party/, built as one static
# library (shaderc_combined) into $(SHADERC_DIR)/lib, its header into $(SHADERC_DIR)/include
$(SHADERC_DIR)/.built: $(SHADERC_TARS)
	rm -rf $(SHADERC_DIR) && mkdir -p $(SHADERC_DIR)/src/third_party/glslang $(SHADERC_DIR)/src/third_party/spirv-tools \
	    $(SHADERC_DIR)/src/third_party/spirv-headers $(SHADERC_DIR)/lib $(SHADERC_DIR)/include
	tar -xzf $(word 1,$^) -C $(SHADERC_DIR)/src --strip-components=1
	tar -xzf $(word 2,$^) -C $(SHADERC_DIR)/src/third_party/glslang --strip-components=1
	tar -xzf $(word 3,$^) -C $(SHADERC_DIR)/src/third_party/spirv-tools --strip-components=1
	tar -xzf $(word 4,$^) -C $(SHADERC_DIR)/src/third_party/spirv-headers --strip-components=1
	$(call CMAKE_BUILD,$(SHADERC_DIR),$(SHADERC_CONF),--target shaderc_combined)
	cp $(SHADERC_DIR)/build/libshaderc/libshaderc_combined.a $(SHADERC_DIR)/lib/
	cp -r $(SHADERC_DIR)/src/libshaderc/include/shaderc $(SHADERC_DIR)/include/
	touch $@
	@echo "shaderc: shaderc $(SHADERC_VER) (glslang $(GLSLANG_VER), SPIRV-Tools $(SPIRV_VER)) built in $(SHADERC_DIR)"

$(SHADERC_DIR)/lib/libshaderc_combined.a: $(SHADERC_DIR)/.built ;

ifneq ($(FFMPEG),system)
$(O)/rt/hle/movie.o: $(FFMPEG_DIR)/.built
$(O)/rt/hle/movie.o: RTFLAGS += -I$(FFMPEG_DIR)/include
endif

# The licenses a copy of the game folder must carry, in $(B)/licenses: this program's own (LICENSE) and its
# THIRD_PARTY_NOTICES (code compiled in: LAS Recomp, Dear ImGui, cimgui, VulkanMemoryAllocator), FFmpeg's LGPL (in the
# executable), and SDL3's and shaderc's (in the programs).
# The pipelines recorded in the common areas (extras/pipelines.list: the game's shader code hashes and render state,
# nothing of the game itself), built in the background on a first run: runtime/nvn/vulkan/exec.c "pipeline list"
pipelist: $(B)/pipelines.list
$(B)/pipelines.list: extras/pipelines.list
	@mkdir -p $(dir $@)
	cp $< $@

LICENSE_TXT = $(B)/licenses/LICENSE.txt $(B)/licenses/THIRD_PARTY_NOTICES.txt $(if $(AV_DEPS),$(B)/licenses/FFmpeg.txt) \
              $(if $(SDL_DEPS),$(B)/licenses/SDL3.txt) $(if $(SHADERC_DEPS),$(B)/licenses/shaderc.txt) \
              $(if $(ZSTD_DEPS),$(B)/licenses/zstd.txt)
licenses: $(LICENSE_TXT)
$(B)/licenses/%.txt: %
	@mkdir -p $(dir $@)
	cp $< $@
$(B)/licenses/FFmpeg.txt: $(FFMPEG_DIR)/.built
	@mkdir -p $(dir $@)
	@{ echo "This program contains FFmpeg $(FFMPEG_VER) (libavformat, libavcodec, libavutil), linked statically, under the"; \
	   echo "GNU Lesser General Public License 2.1 or later (below). Its source code is the release at"; \
	   echo "https://ffmpeg.org/releases/ffmpeg-$(FFMPEG_VER).tar.xz, built with the options in this program's Makefile (FFMPEG_CONF);"; \
	   echo "the program's own source is at https://github.com/pablovesnine/MHGURecomp, to rebuild it with a changed FFmpeg."; \
	   echo; cat $(FFMPEG_DIR)/src/COPYING.LGPLv2.1; } > $@

$(B)/licenses/SDL3.txt: $(SDL3_DIR)/.built
	@mkdir -p $(dir $@)
	@{ echo "This program contains SDL $(SDL3_VER), linked statically, under the zlib license (below). Its source code is"; \
	   echo "https://github.com/libsdl-org/SDL/releases/download/release-$(SDL3_VER)/SDL3-$(SDL3_VER).tar.gz."; \
	   echo; cat $(SDL3_DIR)/src/LICENSE.txt; } > $@
$(B)/licenses/zstd.txt: $(ZSTD_DIR)/.built
	@mkdir -p $(dir $@)
	@{ echo "This program contains zstd $(ZSTD_VER), linked statically under the BSD license (below)."; \
	   echo "Source: https://github.com/facebook/zstd/releases/download/v$(ZSTD_VER)/zstd-$(ZSTD_VER).tar.gz"; \
	   echo; cat $(ZSTD_DIR)/src/LICENSE; } > $@
$(B)/licenses/shaderc.txt: $(SHADERC_DIR)/.built
	@mkdir -p $(dir $@)
	@{ echo "This program contains shaderc $(SHADERC_VER) with glslang $(GLSLANG_VER), SPIRV-Tools $(SPIRV_VER) and SPIRV-Headers"; \
	   echo "$(SPIRV_VER), linked statically, under their licenses (below: shaderc's and SPIRV-Tools' Apache License 2.0,"; \
	   echo "glslang's and SPIRV-Headers' own). Their source code is these releases on GitHub: google/shaderc,"; \
	   echo "KhronosGroup/glslang, KhronosGroup/SPIRV-Tools and KhronosGroup/SPIRV-Headers."; \
	   for f in LICENSE third_party/glslang/LICENSE.txt third_party/spirv-tools/LICENSE third_party/spirv-headers/LICENSE; do \
	     echo; echo "==== $$f"; echo; cat $(SHADERC_DIR)/src/$$f; done; } > $@

$(GAMELIB): $(GEN_OBJ) | $(EXE)
	@mkdir -p $(O)
	$(CC) $(TARGET_FLAGS) $(GAMELIB_LDFLAGS) -o $(O)/gamelib.tmp $^
	mv -f $(O)/gamelib.tmp $@

PY := $(firstword $(wildcard tools/venv/bin/python) python3)

# Explicit convenience target only; Docker never copies the dump into the build.
data: $(B)/data/.complete
$(B)/data/.complete:
	@if [ ! -f "$(GAME)/exefs/main" ] || [ ! -d "$(GAME)/romfs" ]; then \
	    echo "data: no game files in $(GAME) (make GAME=<folder with exefs/ and romfs/>): $(B)/data left empty"; \
	else \
	    mkdir -p $(B)/data && for d in exefs romfs; do \
	        rm -rf "$(B)/data/$$d.tmp"; \
	        cp -rl "$(GAME)/$$d" "$(B)/data/$$d.tmp" 2>/dev/null || { rm -rf "$(B)/data/$$d.tmp"; \
	            echo "data: no hard links here, copying $$d"; cp -r "$(GAME)/$$d" "$(B)/data/$$d.tmp"; } || exit 1; \
	        rm -rf "$(B)/data/$$d" && mv "$(B)/data/$$d.tmp" "$(B)/data/$$d" || exit 1; \
	    done && touch $@ && echo "data: game files in $(B)/data"; \
	fi

gen:
	rm -f "$(GEN)/gen.id" "$(GEN)/gen.id.tmp"
	$(PY) tools/gen.py sdk "$(GAME)/exefs/sdk" 0x02400000 "$(GEN)/sdk" --hle runtime/hle/hle_symbols.txt
	$(PY) tools/gen.py main "$(GAME)/exefs/main" 0x00200000 "$(GEN)/main"
	@printf '%s\n' '$(GEN_ID)' > "$(GEN)/gen.id.tmp"
	@mv -f "$(GEN)/gen.id.tmp" "$(GEN)/gen.id"

.PHONY: check-generated
check-generated:
	@test "$$(cat "$(GEN)/gen.id" 2>/dev/null)" = '$(GEN_ID)' || \
	    { echo "generated code is missing or stale: run make gen GAME=<the game files> first" >&2; exit 1; }

# differential test of the recompiler against Unicorn (tools/test_lift.py)
test-lift:
	$(PY) tools/test_lift.py "$(GAME)/exefs/main" 0x00200000 --tests 6000 --cc "$(CC) $(TARGET_FLAGS) -fuse-ld=lld" --genarch="$(GENARCH)" --runner "$(TEST_RUNNER)"
	$(PY) tools/test_lift.py "$(GAME)/exefs/sdk" 0x02400000 --tests 6000 --cc "$(CC) $(TARGET_FLAGS) -fuse-ld=lld" --genarch="$(GENARCH)" --runner "$(TEST_RUNNER)"

runtime-objs: $(RT_OBJ)

clean:  # (keeps $(B)/data, and the settings, caches and saves wherever the game ran)
	rm -rf $(O) $(B)/*.so $(EXE) $(B)/build-metadata.json

# Internal packaging of an already attested Docker build, never private data.
DIST  ?= dist
CHECK_VERSION = @echo '$(VERSION)' | grep -Eq '^[0-9]+(\.[0-9]+)*$$' || \
	{ echo "dist: '$(VERSION)' is not a release version: make dist VERSION=<the release's tag, e.g. 0.10.4>"; exit 1; }
dist: check-generated
	$(CHECK_VERSION)
	$(PY) tools/dist.py "$(B)" "$(DIST)" linux "$(VERSION)" --revision "$(SOURCE_REVISION)" --image "$(BUILDER_IMAGE)"

.PHONY: all gen test-lift runtime-objs clean data licenses pipelist dist FORCE

# Optional native modules use the same target ABI as the runtime. These targets
# need the upstream 0.14.3 sources; they never install or enable a player module.
ENGMOD_CC   := $(CC) $(TARGET_FLAGS) -O2 -Wall -fsigned-char -fPIC -shared -fuse-ld=lld
ENGMOD_TEST := $(O)/engine-module-test
ENGMOD_SRC  := extras/example-engine-module/example_engine_module.c
.PHONY: example-engine-module test-engine-modules test-cheats
example-engine-module:
	@mkdir -p $(ENGMOD_TEST)/engine_modules/example
	$(ENGMOD_CC) $(ENGMOD_SRC) -o $(ENGMOD_TEST)/engine_modules/example/example.so
	@echo "built $(ENGMOD_TEST)/engine_modules/example: copy the folder to engine_modules/ and add the line 'example' to engine_modules/enabled.txt"

test-engine-modules: $(LIB_STAMPS)
	@rm -rf $(ENGMOD_TEST)/t && mkdir -p $(ENGMOD_TEST)/t/good $(ENGMOD_TEST)/t/hidden $(ENGMOD_TEST)/t/badapi $(ENGMOD_TEST)/t/noapi $(ENGMOD_TEST)/t/declines $(ENGMOD_TEST)/t/notamodule
	$(ENGMOD_CC) $(ENGMOD_SRC) -o $(ENGMOD_TEST)/t/good/good.so
	cp $(ENGMOD_TEST)/t/good/good.so $(ENGMOD_TEST)/t/hidden/hidden.so
	$(ENGMOD_CC) -DEXAMPLE_API=99 $(ENGMOD_SRC) -o $(ENGMOD_TEST)/t/badapi/badapi.so
	$(ENGMOD_CC) -DEXAMPLE_NO_API $(ENGMOD_SRC) -o $(ENGMOD_TEST)/t/noapi/noapi.so
	$(ENGMOD_CC) -DEXAMPLE_DECLINE $(ENGMOD_SRC) -o $(ENGMOD_TEST)/t/declines/declines.so
	printf 'int unrelated;\n' > $(ENGMOD_TEST)/t/notamodule.c
	$(ENGMOD_CC) $(ENGMOD_TEST)/t/notamodule.c -o $(ENGMOD_TEST)/t/notamodule/notamodule.so
	printf '\357\273\277good\n# the loader test\n  badapi  \nnoapi\ndeclines\nnotamodule\nnosuch\n../evil\ngood\n' > $(ENGMOD_TEST)/t/enabled.txt
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(RTFLAGS) tests/test_engine_module.c tests/frame_counter_fixture.c runtime/engine_module.c runtime/config.c runtime/config_store.c $(SDL_LIBS) -ldl -lm -o $(ENGMOD_TEST)/test-engine-module
	MHGU_ENGINE_MODULES_DIR=$(ENGMOD_TEST)/t $(TEST_RUNNER) $(ENGMOD_TEST)/test-engine-module > $(ENGMOD_TEST)/t/out.txt 2>&1 || { cat $(ENGMOD_TEST)/t/out.txt; exit 1; }
	@cat $(ENGMOD_TEST)/t/out.txt
	@for want in 'good: starting' 'good: loaded (Example' '\[example\] port test-version' 'badapi: built for engine module API 99' \
	             'noapi: no mhgu_engine_module_api' 'declines: the module declined' 'notamodule: no mhgu_engine_module_api' \
	             'nosuch: no such folder' '"../evil" is not a folder name' 'engine modules loaded .*: Example' '\[example\] shutdown'; do \
	    grep -q "$$want" $(ENGMOD_TEST)/t/out.txt || { echo "missing in the log: $$want"; exit 1; }; done
	@! grep -q 'hidden' $(ENGMOD_TEST)/t/out.txt || { echo "a module enabled.txt does not list was loaded"; exit 1; }
	@! grep -Eq 'folder .*/(badapi|noapi)' $(ENGMOD_TEST)/t/out.txt || { echo "the entry of a refused module was called"; exit 1; }
	@test "$$(grep -c 'good: loaded' $(ENGMOD_TEST)/t/out.txt)" = 1 || { echo "good loaded twice"; exit 1; }
	@echo "test-engine-modules: OK"

test-cheats: $(LIB_STAMPS)
	@mkdir -p $(O)/settings-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(RTFLAGS) tests/test_cheats.c runtime/cheats.c -lpthread -o $(O)/settings-test/test-cheats
	cd $(O)/settings-test && $(TEST_RUNNER) ./test-cheats

# Exercise real ImGui navigation without a game dump or graphics device.
.PHONY: test-settings-panel
test-settings-panel: $(O)/rt/settings_panel.o $(O)/rt/modorder.o $(O)/rt/arcmerge.o $(O)/rt/config.o $(O)/rt/config_store.o $(O)/imgui/imgui/imgui.o $(O)/imgui/imgui/imgui_draw.o $(O)/imgui/imgui/imgui_tables.o $(O)/imgui/imgui/imgui_widgets.o $(LIB_STAMPS)
	@mkdir -p $(O)/settings-test
	$(CXX) $(TARGET_FLAGS) -fuse-ld=lld $(IMGUIFLAGS) $(PANEL_TEST_FLAGS) -Iruntime tests/test_settings_panel.cpp $(filter %.o,$^) $(SDL_LIBS) -o $(O)/settings-test/test-settings-panel
	$(TEST_RUNNER) $(O)/settings-test/test-settings-panel

# Production font helpers with synthetic inputs; no game files or GPU required.
.PHONY: test-textlayout
test-textlayout:
	@mkdir -p $(O)/textlayout-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld -std=gnu11 -O1 -g -fsigned-char -fno-strict-aliasing -ffunction-sections -fdata-sections -Wl,--gc-sections -Iruntime tests/test_textlayout.c -lz -lm -pthread -o $(O)/textlayout-test/test-textlayout
	$(TEST_RUNNER) $(O)/textlayout-test/test-textlayout

# Production spawn and direct-UDP helpers; synthetic memory and intercepted I/O.
.PHONY: test-villagehub-demo test-ldn-direct
test-villagehub-demo:
	@mkdir -p $(O)/villagehub-demo-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld -std=gnu11 -O1 -g -fsigned-char -fno-strict-aliasing -ffunction-sections -fdata-sections -Wl,--gc-sections -Iruntime tests/test_villagehub_demo.c -o $(O)/villagehub-demo-test/test-villagehub-demo
	$(TEST_RUNNER) $(O)/villagehub-demo-test/test-villagehub-demo

test-ldn-direct:
	@mkdir -p $(O)/ldn-direct-test/include/SDL3 $(O)/ldn-direct-test/include/vulkan
	@printf '%s\n' '#pragma once' 'typedef union SDL_Event SDL_Event;' > $(O)/ldn-direct-test/include/SDL3/SDL.h
	@printf '%s\n' '#pragma once' 'typedef struct VkInstance_T *VkInstance;' 'typedef struct VkPhysicalDevice_T *VkPhysicalDevice;' 'typedef struct VkDevice_T *VkDevice;' 'typedef struct VkQueue_T *VkQueue;' 'typedef struct VkPipelineCache_T *VkPipelineCache;' 'typedef struct VkRenderPass_T *VkRenderPass;' 'typedef struct VkCommandBuffer_T *VkCommandBuffer;' > $(O)/ldn-direct-test/include/vulkan/vulkan.h
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld -std=gnu11 -O1 -g -fsigned-char -fno-strict-aliasing -ffunction-sections -fdata-sections -Wl,--gc-sections -I$(O)/ldn-direct-test/include -Iruntime tests/test_ldn_direct.c -pthread -o $(O)/ldn-direct-test/test-ldn-direct
	$(TEST_RUNNER) $(O)/ldn-direct-test/test-ldn-direct
	$(TEST_RUNNER) $(O)/ldn-direct-test/test-ldn-direct --blocked

# Translation coverage for both host-menu languages; no game files required.
.PHONY: test-settings-locale
test-settings-locale:
	$(PY) tests/test_settings_locale.py

# Real lazy-page faults and fatal signal context; no game files required.
.PHONY: test-linux-fault
test-linux-fault:
	@mkdir -p $(O)/platform-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld -O2 -g -Wall -Wextra -Werror -Iruntime tests/test_linux_fault.c runtime/platform/linux.c -ldl -pthread -o $(O)/platform-test/test-linux-fault
	$(TEST_RUNNER) $(O)/platform-test/test-linux-fault

# Compile both sides of the game-library ABI with their real flag sets.
.PHONY: test-arm64-abi
test-arm64-abi:
	@mkdir -p $(O)/abi-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(RTFLAGS) tests/test_arm64_abi.c -o $(O)/abi-test/runtime
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(GENFLAGS) tests/test_arm64_abi.c -o $(O)/abi-test/generated
	$(TEST_RUNNER) $(O)/abi-test/runtime
	$(TEST_RUNNER) $(O)/abi-test/generated

.PHONY: test-arcmerge
test-arcmerge:
	@mkdir -p $(O)/arc-test
	$(CC) $(TARGET_FLAGS) -fuse-ld=lld $(RTFLAGS) tests/test_arcmerge.c runtime/arcmerge.c -o $(O)/arc-test/test-arcmerge
	$(TEST_RUNNER) $(O)/arc-test/test-arcmerge
