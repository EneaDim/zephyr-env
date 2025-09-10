import os
import re
import argparse
import os
import difflib
from shutil import copyfile
from textwrap import dedent


def write_file(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"Created: {path}")

def update_root_cmakelists(output_folder, module_name):
    cmakelists_path = os.path.join('./', "CMakeLists.txt")
    if not os.path.isfile(cmakelists_path):
        print(f"Warning: {cmakelists_path} does not exist. Skipping update.")
        return

    extra_path = f"${{CMAKE_SOURCE_DIR}}/{output_folder}/{module_name}"
    with open(cmakelists_path, "r") as f:
        lines = f.readlines()

    # Track state
    in_extra_block = False
    block_start = None
    block_end = None
    already_included = False
    cmake_min_line = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("cmake_minimum_required"):
            cmake_min_line = i

        if stripped.startswith("set(ZEPHYR_EXTRA_MODULES"):
            in_extra_block = True
            block_start = i
            if extra_path in line:
                already_included = True
        elif in_extra_block:
            if extra_path in stripped:
                already_included = True
            if ")" in stripped:
                block_end = i
                in_extra_block = False

    # If already present, no need to update
    if already_included:
        print(f"ZEPHYR_EXTRA_MODULES already includes '{extra_path}' — nothing to do.")
        return

    # Modify or insert
    if block_start is not None and block_end is not None:
        # Insert before closing parenthesis
        lines.insert(block_end, f'\t"{extra_path}"\n')
        print(f"Added {extra_path} to existing ZEPHYR_EXTRA_MODULES block.")
    else:
        # Insert new block after cmake_minimum_required
        insert_idx = cmake_min_line + 1 if cmake_min_line is not None else 0
        lines.insert(insert_idx, f'\nset(ZEPHYR_EXTRA_MODULES\n\t"{extra_path}"\n)\n')
        print(f"Inserted new ZEPHYR_EXTRA_MODULES block with {extra_path}.")

    with open(cmakelists_path, "w") as f:
        f.writelines(lines)

def update_root_prjconf(module_name):
    kconfig_path = os.path.join('./', "prj.conf")
    config_name = f"CONFIG_{module_name.upper()}=y\n"

    if not os.path.isfile(kconfig_path):
        print(f"Warning: {kconfig_path} does not exist. Creating new one.")
        with open(kconfig_path, "w") as f:
            f.write(f"CONFIG_SENSOR=y\n")  # minimal starter
            f.write(config_name)
        print(f"Created and updated: {kconfig_path}")
        return

    with open(kconfig_path, "r") as f:
        lines = f.readlines()

    if any(config_name in line for line in lines):
        print(f"{config_name} already present in {kconfig_path}")
        return

    new_lines = []
    inserted = False
    for i, line in enumerate(lines):
        new_lines.append(line)
        if not inserted and line.strip() == "CONFIG_SENSOR=y":
            new_lines.append(config_name)
            inserted = True

    if not inserted:
        # CONFIG_SENSOR=y not found, append at end
        new_lines.append("\nCONFIG_SENSOR=y\n")
        new_lines.append(config_name)

    with open(kconfig_path, "w") as f:
        f.writelines(new_lines)

    print(f"Updated: {kconfig_path} (added {config_name} after CONFIG_SENSOR=y)")

def update_native_sim_overlay(module_name, i2c_addr, interface="i2c0"):
    overlay_path = os.path.join('./boards/native_sim.overlay')

    # Prepare node label and compatible string
    node_parts = module_name.split('_')[:-1]
    node_label = '_'.join(node_parts)
    compat = node_label.replace('_', ',') + "-emul"

    new_node = f"""\
    {node_label}: {node_label}@{i2c_addr} {{
        compatible = "{compat}";
        reg = <0x{i2c_addr}>;
        status = "okay";
        label = "{node_label}";
    }};
"""

    # If overlay file does not exist, create it
    if not os.path.isfile(overlay_path):
        os.makedirs(os.path.dirname(overlay_path), exist_ok=True)
        with open(overlay_path, "w") as f:
            f.write(f"&{interface} {{\n    status = \"okay\";\n{new_node}}};\n")
        print(f"Created and added node to: {overlay_path}")
        return

    with open(overlay_path, "r") as f:
        lines = f.readlines()

    if f"{node_label}@{i2c_addr}" in ''.join(lines):
        print(f"Node '{node_label}@{i2c_addr}' already present in {overlay_path}")
        return

    new_lines = []
    inside_iface = False
    brace_level = 0
    inserted = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith(f"&{interface}"):
            inside_iface = True

        if inside_iface:
            brace_level += line.count("{") - line.count("}")
            if brace_level == 0 and not inserted:
                # Right before the closing brace of &i2c0
                new_lines.append(new_node)
                inserted = True

        new_lines.append(line)

    # If interface block not found, append new full block
    if not inserted:
        print(f"Interface '&{interface}' not found. Appending new block at end.")
        new_lines.append(f"\n&{interface} {{\n    status = \"okay\";\n{new_node}}};\n")

    with open(overlay_path, "w") as f:
        f.writelines(new_lines)

    print(f"Updated: {overlay_path} (added node '{node_label}@{i2c_addr}')")

def update_main_c(
    module_name: str,
    path: str = "./src/main.c",
    *,
    api: str = "sensor",                 # 'sensor' | 'custom'
    channels: list[str] | None = None,   # e.g. ["SENSOR_CHAN_LIGHT"] or ["SENSOR_CHAN_AMBIENT_TEMP","SENSOR_CHAN_HUMIDITY"]
    interval_ms: int = 1000,
    priority: int = 5,
    emul_header: str | None = None,      # e.g. "\"my_driver_emul.h\""
    extra_includes: list[str] | None = None,
    make_backup: bool = True,
    show_diff: bool = False,
) -> bool:
    if not os.path.isfile(path):
        print(f"Error: {path} does not exist.")
        return False

    name = module_name.strip()
    if not name or any(c.isspace() for c in name):
        print("Error: module_name must be a single identifier, e.g. 'sensirion_sht3xd_emul'.")
        return False

    NAME = name.upper()
    channels = (channels or [])[:]
    extra_includes = extra_includes or []

    with open(path, "r", encoding="utf-8") as f:
        original_lines = f.readlines()
    original_str = "".join(original_lines)

    # ---------------------- includes ----------------------
    need_includes = [
        "#include <zephyr/kernel.h>\n",
        "#include <zephyr/device.h>\n",
        "#include <zephyr/devicetree.h>\n",
        "#include <zephyr/logging/log.h>\n",
    ]
    if api == "sensor":
        need_includes.append("#include <zephyr/drivers/sensor.h>\n")
    for inc in extra_includes:
        line = inc if inc.startswith("#include") else f"#include {inc}"
        if not line.endswith("\n"):
            line += "\n"
        if line not in need_includes:
            need_includes.append(line)

    include_inserts = [l for l in need_includes if l not in original_str]

    emul_insert = ""
    if emul_header:
        hdr_line = f"#include {emul_header}\n"
        if hdr_line not in original_str:
            emul_insert = "#ifdef CONFIG_EMUL\n" + hdr_line + "#endif\n"

    # ---------------------- defines / device ----------------------
    # Timing/prio go after LED_BLINK_INTERVAL_MS
    prio_define    = f"#define {NAME}_PRIORITY    {int(priority)}\n"
    timing_define  = f"#define {NAME}_INTERVAL_MS   {int(interval_ms)}\n"
    timing_block = []
    if prio_define not in original_str:
        timing_block.append(prio_define)
    if timing_define not in original_str:
        timing_block.append(timing_define)

    # Device defines go in the "Thread stack and control block" section BEFORE any stacks
    comm_define = f"// {NAME} configuration\n\n"
    node_define = f"#define {NAME}_NODE DT_NODELABEL({name[:-5]})\n"
    dev_decl    = f"static const struct device *{name}_dev = DEVICE_DT_GET({NAME}_NODE);\n"
    device_block = []
    if comm_define not in original_str:
        device_block.append(comm_define)
    if node_define not in original_str:
        device_block.append(node_define)
    if dev_decl not in original_str:
        device_block.append(dev_decl)
    device_block_str = "".join(device_block)

    # Thread defs for this module
    stack_def = f"K_THREAD_STACK_DEFINE({name}_stack, STACK_SIZE);\n"
    tcb_def   = f"static struct k_thread {name}_thread_data;\n"
    thread_defs_block = []
    if stack_def not in original_str:
        thread_defs_block.append(stack_def)
    if tcb_def not in original_str:
        thread_defs_block.append(tcb_def)
    thread_defs_str = "".join(thread_defs_block)

    # ---------------------- thread function ----------------------
    if api == "sensor":
        if not channels:
            channels = ["SENSOR_CHAN_LIGHT"]
        decl_vars = ", ".join([f"val{i}" for i in range(len(channels))]) or "val0"
        if decl_vars == "val0" and channels == []:
            channels = ["SENSOR_CHAN_LIGHT"]

        get_lines = []
        fmt_parts, fmt_args = [], []
        for i, ch in enumerate(channels):
            get_lines.append(f"        && (sensor_channel_get({name}_dev, {ch}, &val{i}) == 0)")
            #label = ch.replace("SENSOR_CHAN_", "")
            label = "SENSOR_CHAN"
            fmt_parts.append(f"{label}={{%.3f}}")
            fmt_args.append(f"sensor_value_to_double(&val{i})")

        thread_func = dedent(f"""
            // {NAME} Thread

            void {name}_thread(void *arg1, void *arg2, void *arg3)
            {{
                struct sensor_value {decl_vars};

                while (1) {{
                    if (sensor_sample_fetch({name}_dev) == 0
            {chr(10).join(get_lines)}) {{
                        LOG_INF("{name}: {' '.join(fmt_parts)}", {', '.join(fmt_args)});
                    }} else {{
                        LOG_WRN("Failed to fetch {name} sample");
                    }}
                    k_msleep({NAME}_INTERVAL_MS);
                }}
            }}
        """).lstrip("\n")
    else:
        thread_func = dedent(f"""
            // {NAME} Thread

            void {name}_thread(void *arg1, void *arg2, void *arg3)
            {{
                while (1) {{
                    // TODO: implement '{name}' work here
                    k_msleep({NAME}_INTERVAL_MS);
                }}
            }}
        """).lstrip("\n")

    # ---------------------- main() injections (by anchors) ----------------------
    # We will:
    # - insert device readiness BEFORE the "LOG_INF(\"LED ready. Launching thread...\")" line
    # - insert driver thread start AFTER the LED thread creation line
    ready_block = dedent(f"""
        /* --- {name} device readiness --- */
        if (!device_is_ready({name}_dev)) {{
            LOG_ERR("{name} not ready");
            return 0;
        }}
    """).rstrip()

    start_block = dedent(f"""
        /* --- {name} Thread --- */
        k_thread_create(&{name}_thread_data, {name}_stack, STACK_SIZE,
                        {name}_thread, NULL, NULL, NULL,
                        {NAME}_PRIORITY, 0, K_NO_WAIT);
    """).rstrip()

    LED_READY_RE   = re.compile(r'LOG_INF\("LED ready\. Launching thread', re.IGNORECASE)
    LED_CREATE_RE  = re.compile(r'k_thread_create\(&\s*led_thread_data\b')

    # ---------------------- build updated file ----------------------
    updated = []
    added_headers = False
    inserted_timing = False
    inserted_device_section = False
    inserted_thread_defs = False
    inserted_thread_func = False
    injected_ready_before_ledready = False
    injected_start_after_ledcreate = False

    THREAD_SECTION_HDR_RE = re.compile(r"Thread stack and control block", re.IGNORECASE)
    STACK_DEFINE_RE       = re.compile(r"^\s*K_THREAD_STACK_DEFINE\(", re.M)

    flag_main = False

    i = 0
    while i < len(original_lines):
        line = original_lines[i]
        stripped = line.strip()
        
        if "int main" in line:
            flag_main = True
        # 1) includes: add after kernel.h
        if not added_headers and stripped == "#include <zephyr/kernel.h>":
            updated.append(line)
            if include_inserts:
                updated.extend(include_inserts)
            if emul_insert:
                updated.append(emul_insert if emul_insert.endswith("\n") else emul_insert + "\n")
            added_headers = True
            i += 1
            continue

        # 2) timing/prio after LED_BLINK_INTERVAL_MS
        if not inserted_timing and stripped.startswith("#define LED_BLINK_INTERVAL_MS"):
            updated.append(line)
            if timing_block:
                updated.append("".join(timing_block))
            inserted_timing = True
            i += 1
            continue

        # 3) device block at start of "Thread stack and control block" section
        if not inserted_device_section and THREAD_SECTION_HDR_RE.search(line):
            if device_block_str:
                updated.append(device_block_str)
            inserted_device_section = True
            updated.append('\n')
            updated.append(line)
            i += 1
            continue

        # 4) place our stack/tcb next to first K_THREAD_STACK_DEFINE
        if not inserted_thread_defs and STACK_DEFINE_RE.match(stripped):
            updated.append(line)
            if thread_defs_str:
                updated.append(thread_defs_str)
            inserted_thread_defs = True
            i += 1
            continue

        # 5) inject our thread function immediately BEFORE 'int main(void)'
        if not inserted_thread_func and stripped.startswith("// Main"):
            if f"void {name}_thread(" not in original_str:
                updated.append(thread_func)
                updated.append('\n')
            inserted_thread_func = True
            # fall-through

        # 6) device readiness BEFORE "LED ready. Launching thread..."
        if (not injected_ready_before_ledready) and LED_READY_RE.search(line):
            if ready_block not in original_str:
                updated.append("    " + ready_block.replace("\n", "\n    ") + "\n")
            injected_ready_before_ledready = True

        # 7) Driver thread create: inject right BEFORE "return 0;"
        if (not injected_start_after_ledcreate) and flag_main and line[0] == "return 0;": #stripped.startswith("K_NO_WAIT"):
            if start_block not in original_str:
                updated.append("\n")  # add a blank line for readability
                updated.append("    " + start_block.replace("\n", "\n    ") + "\n")
            injected_start_after_ledcreate = True

        updated.append(line)

        i += 1

    merged = "".join(updated)

    # ---------------------- fallbacks ----------------------
    # headers
    if not added_headers and (include_inserts or emul_insert):
        header_blob = "".join(include_inserts) + (emul_insert if emul_insert else "")
        merged = header_blob + original_str

    # timing/prio
    if not inserted_timing and timing_block:
        merged += ("\n" if not merged.endswith("\n") else "") + "".join(timing_block)

    # device block before '// Thread...' header; fallback: before first stack define; else append
    if not inserted_device_section and device_block_str:
        THREAD_COMMENT_RE = re.compile(r'^\s*//\s*Thread', re.M)
        m = THREAD_COMMENT_RE.search(merged)
        if m:
            idx = m.start()
            merged = merged[:idx] + device_block_str + merged[idx:]
        else:
            m2 = STACK_DEFINE_RE.search(merged)
            if m2:
                idx = m2.start()
                merged = merged[:idx] + device_block_str + merged[idx:]
            else:
                merged += ("\n" if not merged.endswith("\n") else "") + device_block_str

    # thread defs
    if not inserted_thread_defs and thread_defs_str:
        merged += ("\n" if not merged.endswith("\n") else "") + thread_defs_str

    # thread func
    if not inserted_thread_func and f"void {name}_thread(" not in merged:
        merged += ("\n" if not merged.endswith("\n") else "") + thread_func

    # readiness: if anchor missing, inject near start of main (after '{')
    if not injected_ready_before_ledready and ready_block not in merged:
        # try to inject after opening brace of main
        main_sig = merged.find("int main(void)")
        if main_sig != -1:
            brace_pos = merged.find("{", main_sig)
            if brace_pos != -1:
                brace_pos += 1
                merged = merged[:brace_pos] + "\n    " + ready_block.replace("\n", "\n    ") + "\n" + merged[brace_pos:]
            else:
                merged += "\n/* main() brace not found; appending readiness */\n" + ready_block + "\n"
        else:
            merged += "\n/* main() not found; appending readiness */\n" + ready_block + "\n"

    # start thread: if LED create not found, append near end of main before return 0;
    if not injected_start_after_ledcreate and start_block not in merged:
        # place before final 'return 0;' inside main if possible
        main_start = merged.find("int main(void)")
        if main_start != -1:
            ret_pos = merged.rfind("return 0;", main_start)
            if ret_pos != -1:
                merged = merged[:ret_pos] + "    " + start_block.replace("\n", "\n    ") + "\n    " + merged[ret_pos:]
            else:
                merged += "\n/* LED thread create anchor not found; appending driver start */\n" + start_block + "\n"
        else:
            merged += "\n/* main() not found; appending driver start */\n" + start_block + "\n"

    # ---------------------- write ----------------------
    if merged == original_str:
        print(f"No changes needed for '{name}'.")
        return True

    if make_backup:
        copyfile(path, path + ".bak")
        print(f"Backup created: {path}.bak")

    with open(path, "w", encoding="utf-8") as f:
        f.write(merged)

    if show_diff:
        print("\n".join(difflib.unified_diff(
            original_lines, merged.splitlines(True),
            fromfile=path + " (old)", tofile=path + " (new)", lineterm=""
        )))

    print(f"Updated: {path} (added handler for '{name}')")
    return True

def create_structure(base_path, module_name, interface, category):
    module_path = os.path.join(base_path, module_name)  # module root dir

    # Prepare contents for root files
    cmake_root_content = """\
add_subdirectory(drivers)
zephyr_include_directories(drivers)
"""

    kconfig_root_content = """\
rsource "drivers/Kconfig"
"""

    cmake_drivers_content = f"""\
add_subdirectory_ifdef(CONFIG_{module_name.upper()} {module_name})
"""

    kconfig_drivers_content = f"""\
rsource "{module_name}/Kconfig"
"""

    cmake_emul_content = f"""\
zephyr_library()
zephyr_library_sources({module_name}.c)
zephyr_include_directories(.)
"""

    kconfig_emul_content = f"""\
config {module_name.upper()}
        bool "Emulate {module_name} with {interface} interface"
  default n
        depends on EMUL
        help
          This is an emulator for the {module_name} sensor.
"""

    c_content = f"""\
/*
 * {module_name}.c
 * Interface: {interface}
 */

#define DT_DRV_COMPAT {module_name}  // TODO: assicurati che corrisponda a 'compatible' nel devicetree

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER({'_'.join(module_name.split('_')[-2:])}, CONFIG_{interface.upper()}_LOG_LEVEL);

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/{interface}.h>
#include <zephyr/drivers/{interface}_emul.h>
#include <zephyr/drivers/sensor.h>  // TODO: rimuovi se non è un sensore
#include <zephyr/random/random.h>
#include <string.h>
#include <errno.h>

// -----------------------------------------------------------------------------
// Strutture dati del driver emulato

// TODO: adatta i campi secondo le caratteristiche del tuo dispositivo
struct {module_name}_data {{
    uint16_t raw_data;           // esempio: valore grezzo
    //bool powered_on;
}};

// Configurazione statica
// TODO: estendi se servono altri parametri dal devicetree
struct {module_name}_cfg {{
    uint16_t addr;
}};

// -----------------------------------------------------------------------------
// Funzione di conversione raw → unità fisica (se sensore)

static float raw_to_unit(uint16_t raw)
{{
    // TODO: personalizza la formula secondo il tuo sensore
    return raw / 1.2f;
}}

// -----------------------------------------------------------------------------
// API standard (sensor_driver_api) se usi driver sensor Zephyr

// TODO: rimuovi se non usi il framework sensor

static int {module_name}_sample_fetch(const struct device *dev, enum sensor_channel chan)
{{
    struct {module_name}_data *data = dev->data;
    ARG_UNUSED(chan);

    // Check if powered or not
    //if (!data->powered_on) {{
    //    return -EIO;
    //}}

    data->raw_data = 0x2000 + (sys_rand32_get() % 0x1000);  // TODO: sostituisci con logica realistica
    return 0;
}}

static int {module_name}_channel_get(const struct device *dev,
                                     enum sensor_channel chan,
                                     struct sensor_value *val)
{{
    struct {module_name}_data *data = dev->data;

    // TODO: personalizza il canale
    if (chan != SENSOR_CHAN_LIGHT) {{
        return -EIO;
    }}

    float value = raw_to_unit(data->raw_data);
    sensor_value_from_double(val, value);
    return 0;
}}

static const struct sensor_driver_api {module_name}_driver_api = {{
    .sample_fetch = {module_name}_sample_fetch,
    .channel_get = {module_name}_channel_get,
}};

// -----------------------------------------------------------------------------
// I2C Emulator API

static int {module_name}_transfer(const struct emul *target,
                                  struct {interface}_msg *msgs, int num_msgs, int addr)
{{
    const struct {module_name}_cfg *cfg = target->cfg;
    struct {module_name}_data *data = target->data;

    if (cfg->addr != addr) {{
        return -EIO;
    }}

    // TODO: personalizza la gestione dei comandi I2C

    // Caso: scrittura comando
    if (num_msgs == 1 && !(msgs[0].flags & I2C_MSG_READ)) {{
        uint8_t cmd = msgs[0].buf[0];

        switch (cmd) {{
        case 0x00:  // Power down
            //data->powered_on = false;
            break;
        case 0x01:  // Power on
            //data->powered_on = true;
            break;
        case 0x07:  // Reset
            //if (data->powered_on) {{
            //    data->raw_data = 0;
            //}}
            break;
        case 0x20: case 0x23:  // Modalità misura
            //if (!data->powered_on) return -EIO;
            break;
        default:
            return -EIO;
        }}
        return 0;
    }}

    // Caso: lettura dati (2 byte)
    if (num_msgs == 1 && (msgs[0].flags & I2C_MSG_READ)) {{
        //if (!data->powered_on) return -EIO;
        if (msgs[0].len != 2) return -EIO;

        msgs[0].buf[0] = data->raw_data >> 8;
        msgs[0].buf[1] = data->raw_data & 0xFF;
        return 0;
    }}

    return -EIO;
}}

static struct {interface}_emul_api {module_name}_api = {{
    .transfer = {module_name}_transfer,
}};

// -----------------------------------------------------------------------------
// Inizializzazione dell'emulatore

static int {module_name}_init(const struct emul *target, const struct device *parent)
{{
    struct {module_name}_data *data = target->data;

    //data->powered_on = false;
    data->raw_data = 0x6666;  // TODO: valore iniziale sensato
    return 0;
}}

// -----------------------------------------------------------------------------
// Macro Devicetree per istanziare l’emulatore

#define {module_name.upper()}_EMUL(n) \\
    static struct {module_name}_data {module_name}_data_##n; \\
    static const struct {module_name}_cfg {module_name}_cfg_##n = {{ \\
        .addr = DT_INST_REG_ADDR(n), \\
    }}; \\
    DEVICE_DT_INST_DEFINE(n, NULL, NULL, \\
        &{module_name}_data_##n, &{module_name}_cfg_##n, \\
        POST_KERNEL, I2C_INIT_PRIORITY + 1, &{module_name}_driver_api); \\
    EMUL_DT_INST_DEFINE(n, {module_name}_init, \\
        &{module_name}_data_##n, &{module_name}_cfg_##n, \\
        &{module_name}_api, &{module_name}_driver_api);

DT_INST_FOREACH_STATUS_OKAY({module_name.upper()}_EMUL)
"""

    h_content = f"""\
#ifndef ZEPHYR_DRIVERS_SENSOR_{module_name.upper()}_H_
#define ZEPHYR_DRIVERS_SENSOR_{module_name.upper()}_H_

// -----------------------------------------------------------------------------
// Zephyr core includes

#include <zephyr/device.h>
#include <zephyr/drivers/emul.h>
#include <zephyr/drivers/{interface}_emul.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {{
#endif

/**
 * @brief {module_name.replace('_', ' ').title()} Emulator API
 *
 * API opzionale per test o manipolazione manuale dell'emulatore.
 */
struct {module_name}_api {{
    // TODO: adatta i parametri del metodo 'set' secondo le esigenze del sensore
    int (*set)(const struct device *dev, uint16_t data_raw);
}};

/**
 * @brief Configurazione statica dell'emulatore (da Devicetree)
 */
struct {module_name}_cfg {{
    uint16_t addr;  ///< Indirizzo I2C assegnato nel devicetree
}};

/**
 * @brief Stato dinamico del dispositivo emulato
 */
struct {module_name}_data {{
    struct {interface}_emul emul;     ///< Struttura base Zephyr per I2C emulator
    const struct device *{interface}; ///< Controller I2C associato

    // TODO: personalizza i campi runtime secondo il tuo dispositivo
    uint16_t data_raw;
}};

/**
 * @brief Imposta un valore RAW simulato per l'emulatore
 *
 * Utile per test automatici (ztest) o simulazioni forzate.
 *
 * @param dev        Puntatore al device emulato
 * @param data_raw   Valore grezzo da iniettare
 * @return 0 se ok, -ENOTSUP se API mancante
 */
static inline int {module_name}_set_raw(const struct device *dev, uint16_t data_raw)
{{
    const struct {module_name}_api *api =
        (const struct {module_name}_api *)dev->api;

    if (!api || !api->set) {{
        return -ENOTSUP;
    }}

    return api->set(dev, data_raw);
}}

/**
 * @brief Simula una lettura e restituisce il valore convertito
 *
 * Può essere invocato direttamente in test, senza driver Zephyr.
 *
 * @param emul   Puntatore all'emulatore
 * @param value  Output: unità fisica simulata (es. lux, °C, %RH, ecc.)
 * @return 0 se ok, errore negativo altrimenti
 */
int {module_name}_sample_fetch(const struct emul *emul, float *value);

#ifdef __cplusplus
}}
#endif

#endif  // ZEPHYR_DRIVERS_SENSOR_{module_name.upper()}_H_
"""

    zephyr_module_yaml_content = f"""\
name: {module_name}
build:
  cmake: .
  kconfig: Kconfig
  settings:
    dts_root: .
"""

    # Write root files
    write_file(os.path.join(module_path, "CMakeLists.txt"), cmake_root_content)
    write_file(os.path.join(module_path, "Kconfig"), kconfig_root_content)

    # Write drivers files
    drivers_path = os.path.join(module_path, "drivers")
    write_file(os.path.join(drivers_path, "CMakeLists.txt"), cmake_drivers_content)
    write_file(os.path.join(drivers_path, "Kconfig"), kconfig_drivers_content)

    # Write module driver files
    emul_path = os.path.join(drivers_path, module_name)
    write_file(os.path.join(emul_path, "CMakeLists.txt"), cmake_emul_content)
    write_file(os.path.join(emul_path, "Kconfig"), kconfig_emul_content)
    write_file(os.path.join(emul_path, f"{module_name}.c"), c_content)
    write_file(os.path.join(emul_path, f"{module_name}.h"), h_content)

    # Write DTS YAML file with your filename rule
    yaml_path = os.path.join(module_path, "dts", "bindings", category)
    parts = module_name.split('_', 1)
    if len(parts) == 2:
        first_part = parts[0]
        rest = parts[1].replace('_', '-')
        yaml_filename = f"{first_part},{rest}.yaml"
    else:
        yaml_filename = f"{module_name}.yaml"

    # dts yaml content
    dts_yaml_content = f"""\
description: Emulator for {module_name}

compatible: "{yaml_filename}"

include: [sensor-device.yaml, {interface}-device.yaml]
"""


    write_file(os.path.join(yaml_path, yaml_filename), dts_yaml_content)

    # Write zephyr module.yaml
    write_file(os.path.join(module_path, "zephyr", "module.yaml"), zephyr_module_yaml_content)


def main():
    parser = argparse.ArgumentParser(description="Create Zephyr driver module structure.")
    parser.add_argument("-m", "--module_name", required=True, help="Name of the module, e.g., sensirion_sht3xd_emul")
    parser.add_argument("-i", "--interface", required=True, help="Interface type, e.g., i2c, spi")
    parser.add_argument("-a", "--address", required=True, help="Address at interface node")
    parser.add_argument("-c", "--category", default="sensor", help="Interface type, e.g., i2c, spi")
    parser.add_argument("-o", "--output", default=".", help="Base output directory (default current directory)")

    args = parser.parse_args()

    create_structure(args.output, args.module_name, args.interface, args.category)
    update_root_cmakelists(args.output, args.module_name)
    update_root_prjconf(args.module_name)
    update_native_sim_overlay(args.module_name, args.address)
    update_main_c(args.module_name)

if __name__ == "__main__":
    main()

