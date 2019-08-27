/* gpu-manager:
 *
 * Detect the available GPUs and deal with any system changes, whether
 * software or hardware related
 *
 * Authored by:
 *   Alberto Milone
 *
 *
 * Copyright (C) 2014 Canonical Ltd
 *
 * Based on code from ./hw/xfree86/common/xf86pciBus.c in xorg-server
 * Also based on hybrid-detect.c in ubuntu-drivers-common.
 *
 * Copyright (c) 1997-2003 by The XFree86 Project, Inc.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 * THE COPYRIGHT HOLDER(S) OR AUTHOR(S) BE LIABLE FOR ANY CLAIM, DAMAGES OR
 * OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
 * ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 *
 * Except as contained in this notice, the name of the copyright holder(s)
 * and author(s) shall not be used in advertising or otherwise to promote
 * the sale, use or other dealings in this Software without prior written
 * authorization from the copyright holder(s) and author(s).
 *
 *
 * Build with `gcc -o gpu-manager gpu-manager.c $(pkg-config --cflags --libs pciaccess libdrm)`
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdbool.h>
#include <ctype.h>
#include <pciaccess.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <dirent.h>
#include <getopt.h>
#include <time.h>
#include <fcntl.h>
#include <errno.h>
#include <linux/limits.h>
#include <sys/utsname.h>
#include <libkmod.h>
#include "xf86drm.h"
#include "xf86drmMode.h"

static inline void freep(void *);
static inline void fclosep(FILE **);
static inline void pclosep(FILE **);

#define _cleanup_free_ __attribute__((cleanup(freep)))
#define _cleanup_fclose_ __attribute__((cleanup(fclosep)))
#define _cleanup_pclose_ __attribute__((cleanup(pclosep)))

#define PCI_CLASS_DISPLAY               0x03
#define PCI_CLASS_DISPLAY_OTHER         0x0380

#define PCIINFOCLASSES(c) \
    ( (((c) & 0x00ff0000) \
     == (PCI_CLASS_DISPLAY << 16)) )

#define LAST_BOOT "/var/lib/ubuntu-drivers-common/last_gfx_boot"
#define OFFLOADING_CONF "/var/lib/ubuntu-drivers-common/requires_offloading"
#define XORG_CONF "/etc/X11/xorg.conf"
#define KERN_PARAM "nogpumanager"
#define AMDGPU_PRO_PX  "/opt/amdgpu-pro/bin/amdgpu-pro-px"

#define AMD 0x1002
#define INTEL 0x8086
#define NVIDIA 0x10de

#define MAX_CARDS_N 10

typedef enum {
    SNA,
    MODESETTING,
    UXA
} prime_intel_drv;

typedef enum {
    MODE_POWERSAVING,
    MODE_PERFORMANCE,
    RESET,
    ISPX,
} amdgpu_pro_px_action;

typedef enum {
    ON,
    OFF,
    ONDEMAND
} prime_mode_settings;

static char *log_file = NULL;
static FILE *log_handle = NULL;
static char *last_boot_file = NULL;
static int dry_run = 0;
static char *fake_modules_path = NULL;
static char *gpu_detection_path = NULL;
static char *prime_settings = NULL;
static char *dmi_product_name_path = NULL;
static char *dmi_product_version_path = NULL;
static char *nvidia_driver_version_path = NULL;
static char *amdgpu_pro_px_file = NULL;
static char *modprobe_d_path = NULL;
static char *xorg_conf_d_path = NULL;
static prime_intel_drv prime_intel_driver = SNA;
static prime_mode_settings prime_mode = OFF;

static struct pci_slot_match match = {
    PCI_MATCH_ANY, PCI_MATCH_ANY, PCI_MATCH_ANY, PCI_MATCH_ANY, 0
};

struct device {
    int boot_vga;
    unsigned int vendor_id;
    unsigned int device_id;
    /* BusID components */
    unsigned int domain;
    unsigned int bus;
    unsigned int dev;
    unsigned int func;
    int has_connected_outputs;
};


static bool is_file(char *file);
static bool is_dir(char *directory);
static bool is_dir_empty(char *directory);
static bool is_link(char *file);
static bool is_module_loaded(const char *module);

static inline void freep(void *p) {
    free(*(void**) p);
}


static inline void fclosep(FILE **file) {
    if (*file != NULL && *file >= 0)
        fclose(*file);
}


static inline void pclosep(FILE **file) {
    if (*file != NULL)
        pclose(*file);
}


/* Trim string in place */
static void trim(char *str) {
    char *pointer = str;
    int len = strlen(pointer);

    while(isspace(pointer[len - 1]))
        pointer[--len] = 0;

    while(* pointer && isspace(* pointer)) {
        ++pointer;
        --len;
    }

    memmove(str, pointer, len + 1);
}


static bool starts_with(const char *string, const char *prefix) {
    size_t prefix_len = strlen(prefix);
    size_t string_len = strlen(string);
    return string_len < prefix_len ? 0 : strncmp(prefix, string, prefix_len) == 0;
}


/* Case insensitive equivalent of strstr */
static const char *istrstr(const char *str1, const char *str2) {
    if (!*str2)
    {
      return str1;
    }
    for (; *str1; ++str1) {
        /* Look for the 1st character */
        if (toupper(*str1) == toupper(*str2)) {
            /* We have a match. Let's loop through the
             * remaining characters.
             * chr1 belongs to str1, whereas chr2 belongs to str2.
             */
            const char *chr1, *chr2;
            for (chr1 = str1, chr2 = str2; *chr1 && *chr2; ++chr1, ++chr2) {
                if (toupper(*chr1) != toupper(*chr2)) {
                    break;
                }
            }
            /* If we have matched all of str2 and we have arrived
             * at NULL termination, then we're done.
             * Let's return str1.
             */
            if (!*chr2) {
                return str1;
            }
        }
    }
    return NULL;
}


static bool exists_not_empty(const char *file) {
    struct stat stbuf;

    /* If file doesn't exist */
    if (stat(file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", file);
        return false;
    }
    /* If file is empty */
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size) {
        fprintf(log_handle, "%s is empty\n", file);
        return false;
    }
    return true;
}

#if 0
/* Get reference count from module */
static int get_module_refcount(const char* module) {
    _cleanup_fclose_ FILE *file = NULL;
    _cleanup_free_ char *line = NULL;
    size_t len = 0;
    char refcount_path[50];
    int refcount = 0;
    int status = 0;

    snprintf(refcount_path, sizeof(refcount_path), "/sys/module/%s/refcnt", module);

    if (!exists_not_empty(refcount_path)) {
        fprintf(log_handle, "Error: %s does not exist or is empty.\n", refcount_path);
        return 0;
    }

    /* get dmi product version */
    file = fopen(refcount_path, "r");
    if (file == NULL) {
        fprintf(log_handle, "can't open %s\n", refcount_path);
        return 0;
    }
    if (getline(&line, &len, file) == -1) {
        fprintf(log_handle, "can't get line from %s\n", refcount_path);
        return 0;
    }

    status = sscanf(line, "%d\n", &refcount);

    /* Make sure that we match 1 time */
    if (status == EOF || status != 1)
        refcount = 0;

    return refcount;
}
#endif


static bool act_upon_module_with_params(const char *module,
                                       int mode,
                                       char *params) {
    int status = 0;
    char command[300];

    fprintf(log_handle, "%s %s with \"%s\" parameters\n",
            mode ? "Loading" : "Unloading",
            module, params ? params : "no");

    if (params) {
        snprintf(command, sizeof(command), "%s %s %s",
                 mode ? "/sbin/modprobe" : "/sbin/rmmod",
                 module, params);
        free(params);
    }
    else {
        snprintf(command, sizeof(command), "%s %s",
                 mode ? "/sbin/modprobe" : "/sbin/rmmod",
                 module);
    }

    if (dry_run)
        return true;

    status = system(command);

    return (status == 0);
}

/* Load a kernel module and pass it parameters */
static bool load_module_with_params(const char *module,
                                   char *params) {
    return (act_upon_module_with_params(module, 1, params));
}


/* Load a kernel module */
static bool load_module(const char *module) {
    return (load_module_with_params(module, NULL));
}


/* Unload a kernel module */
static bool unload_module(const char *module) {
    return (act_upon_module_with_params(module, 0, NULL));
}


/* Get the first match from the output of a command */
static char* get_output(const char *command, const char *pattern, const char *ignore) {
    int len;
    char buffer[1035];
    char *output = NULL;
    _cleanup_pclose_ FILE *pfile = NULL;
    pfile = popen(command, "r");
    if (pfile == NULL) {
        fprintf(stderr, "Failed to run command %s\n", command);
        return NULL;
    }

    while (fgets(buffer, sizeof(buffer), pfile)) {
        /* If no search pattern was provided, just
         * return the first non zero legth line
         */
        if (!pattern) {
            output = strdup(buffer);
            break;
        }
        else {
            /* Look for the search pattern */
            if (ignore && (strstr(buffer, ignore) != NULL)) {
                /* Skip this line */
                continue;
            }
            /* Look for the pattern */
            if (strstr(buffer, pattern) != NULL) {
                output = strdup(buffer);
                break;
            }
        }
    }

    if (output) {
        /* Remove newline */
        len = strlen(output);
        if(output[len-1] == '\n' )
           output[len-1] = 0;
    }
    return output;
}


static bool is_module_blacklisted(const char* module) {
    _cleanup_free_ char *match = NULL;
    char command[100];

    /* It will be a file if it's a test */
    if (dry_run) {
        snprintf(command, sizeof(command),
                 "grep -G \"blacklist.*%s[[:space:]]*$\" %s",
                 module, modprobe_d_path);

        if (exists_not_empty(modprobe_d_path))
            match = get_output(command, NULL, NULL);
    }
    else {
        snprintf(command, sizeof(command),
                 "grep -G \"^blacklist.*%s[[:space:]]*$\" %s/*.conf",
                 module, modprobe_d_path);

        match = get_output(command, NULL, NULL);

        if (!match) {
            snprintf(command, sizeof(command),
                 "grep -G \"^blacklist.*%s[[:space:]]*$\" %s/*.conf",
                 module, "/lib/modprobe.d");

            match = get_output(command, NULL, NULL);
        }
    }

    if (!match)
        return false;
    return true;
}


/* Look for unloaded modules */
static bool has_unloaded_module(char *module) {
    char path[PATH_MAX];

    snprintf(path, sizeof(path), "%s/u-d-c-%s-was-loaded",
             gpu_detection_path, module);

    if (is_file(path) && !is_module_loaded(module)) {
        fprintf(log_handle, "%s was unloaded\n", module);
        return true;
    }

    return false;
}


static bool find_string_in_file(const char *path, const char *pattern) {
    _cleanup_free_ char *line = NULL;
    _cleanup_fclose_ FILE *file = NULL;
    size_t len = 0;
    size_t read;

    bool found = false;

    file = fopen(path, "r");
    if (file == NULL)
         return found;
    while ((read = getline(&line, &len, file)) != -1) {
        if (istrstr(line, pattern) != NULL) {
            found = true;
            break;
        }
    }

    return found;
}


static bool is_file_empty(const char *file) {
    struct stat stbuf;

    if (stat(file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", file);
        return false;
    }
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size)
        return true;

    return false;
}


static bool has_cmdline_option(const char *option)
{
    return (find_string_in_file("/proc/cmdline", option));
}


static bool is_disabled_in_cmdline() {
    return has_cmdline_option(KERN_PARAM);
}


static prime_intel_drv get_prime_intel_driver() {
    prime_intel_drv driver;
    if (has_cmdline_option("gpumanager_modesetting")) {
        driver = MODESETTING;
        fprintf(log_handle, "Detected boot parameter to force the modesetting driver\n");
    }
    else if (has_cmdline_option("gpumanager_uxa")) {
        driver = UXA;
        fprintf(log_handle, "Detected boot parameter to force Intel/UXA\n");
    }
    else if (has_cmdline_option("gpumanager_sna")) {
        driver = SNA;
        fprintf(log_handle, "Detected boot parameter to force Intel/SNA\n");
    }
    else {
        driver = MODESETTING;
    }

    return driver;
}


static bool copy_file(const char *src_path, const char *dst_path)
{
    _cleanup_fclose_ FILE *src = NULL;
    _cleanup_fclose_ FILE *dst = NULL;
    int src_fd, dst_fd;
    int n = 0;
    char buf[BUFSIZ];

    src = fopen(src_path, "r");
    if (src == NULL) {
        fprintf(log_handle, "error: can't open %s for reading\n", src_path);
        return false;
    }

    dst = fopen(dst_path, "w");
    if (dst == NULL) {
        fprintf(log_handle, "error: can't open %s for writing.\n",
                dst_path);
        return false;
    }

    src_fd = fileno(src);
    dst_fd = fileno(dst);

    fprintf(log_handle, "copying %s to %s...\n", src_path, dst_path);

    while ((n = read(src_fd, buf, BUFSIZ)) > 0)
        if (write(dst_fd, buf, n) != n) {
            fprintf(log_handle, "write error on file %s\n", dst_path);
            return false;
        }

    fprintf(log_handle, "%s was copied successfully to %s\n", src_path, dst_path);
    return true;
}


/* Open a file and check if it contains "on"
 * or "off".
 *
 * Return false if the file doesn't exist or is empty.
 */
static bool check_on_off(const char *path) {
    bool status = false;
    char line[100];
    _cleanup_fclose_ FILE *file = NULL;

    file = fopen(path, "r");

    if (!file) {
        fprintf(log_handle, "Error: can't open %s\n", path);
        return false;
    }

    while (fgets(line, sizeof(line), file)) {
        if (istrstr(line, "on") != NULL) {
            status = true;
            break;
        }
    }

    return status;
}


/* Get the settings for PRIME.
 *
 * This tells us whether the discrete card should be
 * on or off.
 */
static bool prime_is_action_on() {
    return (check_on_off(prime_settings));
}


static void get_prime_action() {
    char line[100];
    _cleanup_fclose_ FILE *file = NULL;

    file = fopen(prime_settings, "r");

    if (!file) {
        fprintf(log_handle, "Error: can't open %s\n", prime_settings);
        prime_mode = OFF;
    }

    while (fgets(line, sizeof(line), file)) {
        if (istrstr(line, "on-demand") != NULL) {
            prime_mode = ONDEMAND;
            break;
        }
        else if (istrstr(line, "on") != NULL) {
            prime_mode = ON;
            break;
        }
        else {
            prime_mode = OFF;
            break;
        }
    }
}

static void get_boot_vga(struct device **devices,
                        int cards_number,
                        unsigned int *vendor_id,
                        unsigned int *device_id) {
    int i;
    for(i = 0; i < cards_number; i++) {
        if (devices[i]->boot_vga) {
            *vendor_id = devices[i]->vendor_id;
            *device_id = devices[i]->device_id;
            break;
        }
    }
}


static void get_first_discrete(struct device **devices,
                               int cards_number,
                               struct device *device) {
    int i;
    for(i = 0; i < cards_number; i++) {
        if (!devices[i]->boot_vga) {
            memcpy(device, devices[i], sizeof(struct device));
            break;
        }
    }
}


static bool has_system_changed(struct device **old_devices,
                       struct device **new_devices,
                       int old_number,
                       int new_number) {

    bool status = false;
    int i;
    if (old_number != new_number) {
        fprintf(log_handle, "The number of cards has changed!\n");
        return 1;
    }

    for (i = 0; i < old_number; i++) {
        if ((old_devices[i]->boot_vga != new_devices[i]->boot_vga) ||
            (old_devices[i]->vendor_id != new_devices[i]->vendor_id) ||
            (old_devices[i]->device_id != new_devices[i]->device_id) ||
            (old_devices[i]->domain != new_devices[i]->domain) ||
            (old_devices[i]->bus != new_devices[i]->bus) ||
            (old_devices[i]->dev != new_devices[i]->dev) ||
            (old_devices[i]->func != new_devices[i]->func)) {
            status = true;
            break;
        }
    }

    return status;
}


static bool write_data_to_file(struct device **devices,
                              int cards_number,
                              char *filename) {
    int i;
    _cleanup_fclose_ FILE *file = NULL;
    file = fopen(filename, "w");
    if (file == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                filename);
        return false;
    }

    for(i = 0; i < cards_number; i++) {
        fprintf(file, "%04x:%04x;%04x:%02x:%02x:%d;%d\n",
                devices[i]->vendor_id,
                devices[i]->device_id,
                devices[i]->domain,
                devices[i]->bus,
                devices[i]->dev,
                devices[i]->func,
                devices[i]->boot_vga);
    }
    fflush(file);

    return true;
}


static int get_vars(const char *line, struct device **devices,
                    int num, int desired_matches) {
    int status;

    devices[num] = malloc(sizeof(struct device));

    if (!devices[num])
        return EOF;

    status = sscanf(line, "%04x:%04x;%04x:%02x:%02x:%d;%d\n",
                    &devices[num]->vendor_id,
                    &devices[num]->device_id,
                    &devices[num]->domain,
                    &devices[num]->bus,
                    &devices[num]->dev,
                    &devices[num]->func,
                    &devices[num]->boot_vga);

    /* Make sure that we match "desired_matches" */
    if (status == EOF || status != desired_matches)
        free(devices[num]);

    return status;
}


/* Return 0 if it failed, 1 if it succeeded,
 * 2 if it created the file for the first time
 */
static int read_data_from_file(struct device **devices,
                               int *cards_number,
                               char *filename) {
    /* Read from last boot gfx */
    char line[100];
    _cleanup_fclose_ FILE *file = NULL;
    /* The number of digits we expect to match per line */
    int desired_matches = 7;
    int created = 1;

    file = fopen(filename, "r");
    if (file == NULL) {
        created = 2;
        fprintf(log_handle, "I couldn't open %s for reading.\n", filename);
        /* Create the file for the 1st time */
        file = fopen(filename, "w");
        fprintf(log_handle, "Create %s for the 1st time\n", filename);
        if (file == NULL) {
            fprintf(log_handle, "I couldn't open %s for writing.\n",
                    filename);
            return 0;
        }
        fprintf(file, "%04x:%04x;%04x:%02x:%02x:%d;%d\n",
                0, 0, 0, 0, 0, 0, 0);
        fflush(file);
        fclose(file);
        /* Try again */
        file = fopen(filename, "r");
    }

    if (file == NULL) {
        fprintf(log_handle, "I couldn't open %s for reading.\n", filename);
        return 0;
    }
    else {
        /* Use fgets so as to limit the buffer length */
        while (fgets(line, sizeof(line), file) && (*cards_number < MAX_CARDS_N)) {
            if (strlen(line) > 0) {
                /* See if we actually get all the desired digits,
                 * as per "desired_matches"
                 */
                if (get_vars(line, devices, *cards_number, desired_matches) == desired_matches) {
                    *cards_number += 1;
                }
            }
        }
    }

    return created;
}


static void add_gpu_from_file(char *filename, char *dirname, struct device **devices,
                              int *cards_number)
{
    int status = EOF;
    char path[PATH_MAX];
    char pattern[] = "u-d-c-gpu-%04x:%02x:%02x.%d-0x%04x-0x%04x";

    fprintf(log_handle, "Adding GPU from file: %s\n", filename);

    /* The number of digits we expect to match in the name */
    int desired_matches = 6;

    devices[*cards_number] = malloc(sizeof(struct device));
    if (!devices[*cards_number])
    return;

    /* The name pattern will look like the following:
     * u-d-c-gpu-0000:09:00.0-0x10de-0x1140
     */
    sprintf(path, "%s/%s", dirname, pattern);

    /* Extract the data from the string */
    status = sscanf(filename, path,
                    &devices[*cards_number]->domain,
                    &devices[*cards_number]->bus,
                    &devices[*cards_number]->dev,
                    &devices[*cards_number]->func,
                    &devices[*cards_number]->vendor_id,
                    &devices[*cards_number]->device_id);

    /* Check that we actually matched all the desired digits,
     * as per "desired_matches"
     */
    if (status == EOF || status != desired_matches) {
        free(devices[*cards_number]);
        fprintf(log_handle, "no matches, status = %d, expected = %d\n", status, desired_matches);
        return;
    }

    devices[*cards_number]->has_connected_outputs = -1;

    fprintf(log_handle, "Adding %04x:%04x in PCI:%02x@%04x:%02x:%d to the list\n",
            devices[*cards_number]->vendor_id, devices[*cards_number]->device_id,
            devices[*cards_number]->bus, devices[*cards_number]->domain,
            devices[*cards_number]->dev, devices[*cards_number]->func);

    /* Increment number of cards */
    *cards_number += 1;

    fprintf(log_handle, "Successfully detected disabled cards. Total number is %d now\n",
            *cards_number);
}


/* Look for clues of disabled cards in the directory */
void find_disabled_cards(char *dir, struct device **devices,
                         int *cards_n, void (*fcn)(char *, char *,
                         struct device **, int *))
{
    char name[PATH_MAX];
    struct dirent *dp;
    DIR *dfd;

    fprintf(log_handle, "Looking for disabled cards in %s\n", dir);

    if ((dfd = opendir(dir)) == NULL) {
        fprintf(stderr, "Error: can't open %s\n", dir);
        return;
    }

    while ((dp = readdir(dfd)) != NULL) {
        if (!starts_with(dp->d_name, "u-d-c-gpu-"))
            continue;
        if (strlen(dir)+strlen(dp->d_name)+2 > sizeof(name))
            fprintf(stderr, "Error: name %s/%s too long\n",
                    dir, dp->d_name);
        else {
            sprintf(name, "%s/%s", dir, dp->d_name);
            (*fcn)(name, dir, devices, cards_n);
        }
    }
    closedir(dfd);
}


/* Check if a kernel module is available for the current kernel */
static bool is_module_available(const char *module)
{
    char dir[PATH_MAX];
    struct dirent *dp;
    DIR *dfd;
    struct utsname uname_data;
    bool status = false;

    if (uname(&uname_data) < 0) {
        fprintf(stderr, "Error: uname failed\n");
        return false;
    }

    sprintf(dir, "/lib/modules/%s/updates/dkms", uname_data.release);

    fprintf(log_handle, "Looking for %s modules in %s\n", module, dir);

    if ((dfd = opendir(dir)) == NULL) {
        fprintf(stderr, "Error: can't open %s\n", dir);
        return false;
    }

    while ((dp = readdir(dfd)) != NULL) {
        if (!starts_with(dp->d_name, module))
            continue;

        status = true;
        fprintf(log_handle, "Found %s module: %s\n", module, dp->d_name);
        break;
    }
    closedir(dfd);

    return status;
}


static bool is_module_loaded(const char *module) {
    bool status = false;
    char line[4096];
    _cleanup_fclose_ FILE *file = NULL;

    if (!fake_modules_path)
        file = fopen("/proc/modules", "r");
    else
        file = fopen(fake_modules_path, "r");

    if (!file) {
        fprintf(log_handle, "Error: can't open /proc/modules");
        return false;
    }

    while (fgets(line, sizeof(line), file)) {
        char *tok;
        tok = strtok(line, " \t");
        if (strstr(tok, module) != NULL) {
            status = true;
            break;
        }
    }

    return status;
}


static bool is_file(char *file) {
    struct stat stbuf;

    if (stat(file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s file\n", file);
        return false;
    }
    if (stbuf.st_mode & S_IFMT)
        return true;

    return false;
}


static bool is_dir(char *directory) {
    struct stat stbuf;

    if (stat(directory, &stbuf) == -1) {
        fprintf(log_handle, "Error: can't access %s\n", directory);
        return false;
    }
    if ((stbuf.st_mode & S_IFMT) == S_IFDIR)
        return true;
    return false;
}


static bool is_dir_empty(char *directory) {
    int n = 0;
    struct dirent *d;
    DIR *dir = opendir(directory);
    if (dir == NULL)
        return true;
    while ((d = readdir(dir)) != NULL) {
        if(++n > 2)
        break;
    }
    closedir(dir);
    if (n <= 2)
        return true;
    else
        return false;
}


static bool is_link(char *file) {
    struct stat stbuf;

    if (lstat(file, &stbuf) == -1) {
        fprintf(log_handle, "Error: can't access %s\n", file);
        return false;
    }
    if ((stbuf.st_mode & S_IFMT) == S_IFLNK)
        return true;

    return false;
}


/* See if the device is bound to a driver */
static bool is_device_bound_to_driver(struct pci_device *info) {
    char sysfs_path[1024];
    snprintf(sysfs_path, sizeof(sysfs_path),
             "/sys/bus/pci/devices/%04x:%02x:%02x.%d/driver",
             info->domain, info->bus, info->dev, info->func);

    return(is_link(sysfs_path));
}


/* See if the device is a pci passthrough */
static bool is_device_pci_passthrough(struct pci_device *info) {
    enum { BUFFER_SIZE = 1024 };
    char buf[BUFFER_SIZE], sysfs_path[BUFFER_SIZE], *drv, *name;
    ssize_t length;

    length = snprintf(sysfs_path, sizeof(sysfs_path),
                      "/sys/bus/pci/devices/%04x:%02x:%02x.%d/driver",
                      info->domain, info->bus, info->dev, info->func);
    if (length < 0 || length >= sizeof(sysfs_path))
        return false;

    length = readlink(sysfs_path, buf, sizeof(buf)-1);

    if (length != -1) {
        buf[length] = '\0';

        if ((drv = strrchr(buf, '/')))
            name = drv+1;
        else
            name = buf;

        if (strcmp(name, "pci-stub") == 0 || strcmp(name, "pciback") == 0)
            return true;
    }
    return false;
}


/* Check the drm connector status */
static bool is_connector_connected(const char *connector) {
    bool status = false;
    char line[50];
    _cleanup_fclose_ FILE *file = NULL;

    file = fopen(connector, "r");

    if (!file)
        return false;

    while (fgets(line, sizeof(line), file)) {
        char *tok;
        tok = strtok(line, " \t");
        if (starts_with(tok, "connected")) {
            status = true;
            break;
        }
    }

    return status;
}


/* Count the number of outputs connected to the card */
int count_connected_outputs(const char *device_name) {
    char name[PATH_MAX];
    struct dirent *dp;
    DIR *dfd;
    int connected_outputs = 0;
    char drm_dir[] = "/sys/class/drm";

    if ((dfd = opendir(drm_dir)) == NULL) {
        fprintf(stderr, "Warning: can't open %s\n", drm_dir);
        return connected_outputs;
    }

    while ((dp = readdir(dfd)) != NULL) {
        if (!starts_with(dp->d_name, device_name))
            continue;
        if (strlen(drm_dir)+strlen(dp->d_name)+2 > sizeof(name))
            fprintf(stderr, "Warning: name %s/%s too long\n",
                    drm_dir, dp->d_name);
        else {
            /* Open the file for the connector */
            snprintf(name, sizeof(name), "%s/%s/status", drm_dir, dp->d_name);
            name[sizeof(name) - 1] = 0;
            if (is_connector_connected(name)) {
                fprintf(log_handle, "output %d:\n", connected_outputs);
                fprintf(log_handle, "\t%s\n", dp->d_name);
                connected_outputs++;
            }
        }
    }
    closedir(dfd);

    return connected_outputs;
}


/* See if the drm device created by a driver has any connected outputs.
 * Return 1 if outputs are connected, 0 if they're not, -1 if unknown
 */
static int has_driver_connected_outputs(const char *driver) {
    DIR *dir;
    struct dirent* dir_entry;
    char path[PATH_MAX];
    int fd = 1;
    drmVersionPtr version;
    int connected_outputs = 0;
    int driver_match = 0;
    char dri_dir[] = "/dev/dri";
    _cleanup_free_ char *device_path= NULL;

    if (NULL == (dir = opendir(dri_dir))) {
        fprintf(log_handle, "Error : Failed to open %s\n", dri_dir);
        return -1;
    }

    /* Keep looking until we find the device for the driver */
    while ((dir_entry = readdir(dir))) {
        if (!starts_with(dir_entry->d_name, "card"))
            continue;

        snprintf(path, sizeof(path), "%s/%s", dri_dir, dir_entry->d_name);
        path[sizeof(path) - 1] = 0;
        fd = open(path, O_RDWR);
        if (fd) {
            if ((version = drmGetVersion(fd))) {
                /* Let's use strstr to catch the different backported
                 * kernel modules
                 */
                if (driver && strstr(version->name, driver) != NULL) {
                    fprintf(log_handle, "Found \"%s\", driven by \"%s\"\n",
                           path, version->name);
                    driver_match = 1;
                    device_path = malloc(strlen(dir_entry->d_name)+1);
                    if (device_path)
                        strcpy(device_path, dir_entry->d_name);
                    drmFreeVersion(version);
                    break;
                }
                else {
                    fprintf(log_handle, "Skipping \"%s\", driven by \"%s\"\n",
                            path, version->name);
                    drmFreeVersion(version);
                    close(fd);
                }
            }
        }
        else {
            fprintf(log_handle, "Error: can't open fd for %s\n", path);
            continue;
        }
    }

    closedir(dir);

    close(fd);

    if (!driver_match)
        return -1;

    if (!device_path)
        return -1;

    connected_outputs = count_connected_outputs(device_path);

    fprintf(log_handle, "Number of connected outputs for %s: %d\n", path, connected_outputs);

    return (connected_outputs > 0);
}


/* Add information on connected outputs */
static void add_connected_outputs_info(struct device **devices,
                                       int cards_n) {
    int i;
    int amdgpu_has_outputs = has_driver_connected_outputs("amdgpu");
    int radeon_has_outputs = has_driver_connected_outputs("radeon");
    int nouveau_has_outputs = has_driver_connected_outputs("nouveau");
    int intel_has_outputs = has_driver_connected_outputs("i915");

    for(i = 0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL)
            devices[i]->has_connected_outputs = intel_has_outputs;
        else if (devices[i]->vendor_id == AMD)
            devices[i]->has_connected_outputs = ((radeon_has_outputs != -1) ? radeon_has_outputs
                                                 : amdgpu_has_outputs);
        else if (devices[i]->vendor_id == NVIDIA)
            devices[i]->has_connected_outputs = nouveau_has_outputs;
        else
            devices[i]->has_connected_outputs = -1;
    }
}


/* Check if any outputs are still connected to card0.
 *
 * By default we only check cards driver by i915.
 * If so, then claim support for RandR offloading
 */
static bool requires_offloading(struct device **devices,
                                int cards_n) {

    /* Let's check only /dev/dri/card0 and look
     * for driver i915. We don't want to enable
     * offloading to any other driver, as results
     * may be unpredictable
     */
    int i;
    bool status = false;
    for(i = 0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL) {
            status = (devices[i]->has_connected_outputs == 1);
            break;
        }
    }

    return status;
}


/* Set permanent settings for offloading */
static bool set_offloading(void) {
    _cleanup_fclose_ FILE *file = NULL;

    if (dry_run)
        return true;

    file = fopen(OFFLOADING_CONF, "w");
    if (file != NULL) {
        fprintf(file, "ON\n");
        fflush(file);
        return true;
    }

    return false;
}


/* Move the log */
static bool move_log(void) {
    int status;
    char backup[200];
    char buffer[80];
    time_t rawtime;
    struct tm *info;

    time(&rawtime);
    info = localtime(&rawtime);

    strftime(buffer, 80, "%H%M%m%d%Y", info);
    snprintf(backup, sizeof(backup), "%s.%s", log_file, buffer);

    status = rename(log_file, backup);
    if (!status) {
        status = unlink(log_file);
        if (!status)
            return false;
        else
            return true;
    }

    return true;
}


static bool create_prime_settings(const char *prime_settings) {
    _cleanup_fclose_ FILE *file = NULL;

    fprintf(log_handle, "Trying to create new settings for prime. Path: %s\n",
            prime_settings);

    file = fopen(prime_settings, "w");
    if (file == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                prime_settings);
        return false;
    }
    /* Set prime to "on" */
    fprintf(file, "on\n");
    fflush(file);

    return true;
}


static bool get_nvidia_driver_version(int *major, int *minor) {

    int status;
    size_t len = 0;
    _cleanup_free_ char *driver_version = NULL;
    _cleanup_fclose_ FILE *file = NULL;

    /* Check the driver version */
    file = fopen(nvidia_driver_version_path, "r");
    if (file == NULL) {
        fprintf(log_handle, "can't open %s\n", nvidia_driver_version_path);
        return false;
    }
    if (getline(&driver_version, &len, file) == -1) {
        fprintf(log_handle, "can't get line from %s\n", nvidia_driver_version_path);
        return false;
    }

    status = sscanf(driver_version, "%d.%d\n", major, minor);

    /* Make sure that we match "desired_matches" */
    if (status == EOF || status != 2) {
        fprintf(log_handle, "Warning: couldn't get the driver version from %s\n",
                nvidia_driver_version_path);
        return false;
    }

    return true;
}


static char* get_module_version(const char *module_name) {
    struct kmod_ctx *ctx = NULL;
    struct kmod_module *mod = NULL;
    struct kmod_list *l, *list = NULL;
    int err;
    char *version = NULL;

    ctx = kmod_new(NULL, NULL);
    err = kmod_module_new_from_name(ctx, module_name, &mod);
    if (err < 0) {
        fprintf(log_handle, "can't acquire module via kmod");
        goto get_module_version_clean;
    }

    err = kmod_module_get_info(mod, &list);
    if (err < 0) {
        fprintf(log_handle, "can't get module info via kmod");
        goto get_module_version_clean;
    }

    kmod_list_foreach(l, list) {
        const char *key = kmod_module_info_get_key(l);

        if (strcmp(key, "version") == 0) {
            version = strdup(kmod_module_info_get_value(l));
            break;
        }
    }

get_module_version_clean:
    if (list)
        kmod_module_info_free_list(list);
    if (mod)
        kmod_module_unref(mod);
    if (ctx)
        kmod_unref(ctx);

    return version;
}


static bool is_module_versioned(const char *module_name) {
    _cleanup_free_ const char *version = NULL;

    if (dry_run)
        return false;

    version = get_module_version(module_name);

    return version ? true : false;
}


static bool run_amdgpu_pro_px(amdgpu_pro_px_action action) {
    int status = 0;
    char command[100];

    switch (action) {
    case MODE_POWERSAVING:
        snprintf(command, sizeof(command), "%s --%s", amdgpu_pro_px_file, "mode powersaving");
        fprintf(log_handle, "Enabling power saving mode for amdgpu-pro");
        break;
    case MODE_PERFORMANCE:
        snprintf(command, sizeof(command), "%s --%s", amdgpu_pro_px_file, "mode performance");
        fprintf(log_handle, "Enabling performance mode for amdgpu-pro");
        break;
    case RESET:
        snprintf(command, sizeof(command), "%s --%s", amdgpu_pro_px_file, "reset");
        fprintf(log_handle, "Resetting the script changes for amdgpu-pro");
        break;
    case ISPX:
        snprintf(command, sizeof(command), "%s --%s", amdgpu_pro_px_file, "ispx");
        break;
    }

    if (dry_run) {
        fprintf(log_handle, "%s\n", command);
        return true;
    }

    status = system(command);

    return (status == 0);
}


static bool create_prime_outputclass(void) {
    _cleanup_fclose_ FILE *file = NULL;
    _cleanup_free_ char *multiarch = NULL;
    char command[100];
    char xorg_d_custom[PATH_MAX];

    snprintf(xorg_d_custom, sizeof(xorg_d_custom), "%s/11-nvidia-prime.conf",
             xorg_conf_d_path);

    snprintf(command, sizeof(command),
             "/usr/bin/dpkg-architecture -qDEB_HOST_MULTIARCH");

    multiarch = get_output(command, NULL, NULL);
    if (!multiarch)
        return false;

    fprintf(log_handle, "Creating %s\n", xorg_d_custom);
    file = fopen(xorg_d_custom, "w");
    if (!file) {
        fprintf(log_handle, "Error while creating %s\n", xorg_d_custom);
    }
    else {
        fprintf(file,
                "# DO NOT EDIT. AUTOMATICALLY GENERATED BY gpu-manager\n\n"
                "Section \"OutputClass\"\n"
                "    Identifier \"Nvidia Prime\"\n"
                "    MatchDriver \"nvidia-drm\"\n"
                "    Driver \"nvidia\"\n"
                "    Option \"AllowEmptyInitialConfiguration\"\n"
                "    Option \"IgnoreDisplayDevices\" \"CRT\"\n"
                "    Option \"PrimaryGPU\" \"Yes\"\n"
                "    ModulePath \"/%s/nvidia/xorg\"\n"
                "EndSection\n\n",
                multiarch);

        fflush(file);
        return true;
    }

    return false;
}

static bool create_offload_serverlayout(void) {
    _cleanup_fclose_ FILE *file = NULL;
    char xorg_d_custom[PATH_MAX];

    snprintf(xorg_d_custom, sizeof(xorg_d_custom), "%s/11-nvidia-offload.conf",
             xorg_conf_d_path);

    fprintf(log_handle, "Creating %s\n", xorg_d_custom);
    file = fopen(xorg_d_custom, "w");
    if (!file) {
        fprintf(log_handle, "Error while creating %s\n", xorg_d_custom);
    }
    else {
        fprintf(file,
                "# DO NOT EDIT. AUTOMATICALLY GENERATED BY gpu-manager\n\n"
                "Section \"ServerLayout\"\n"
                "    Identifier \"layout\"\n"
                "    Option \"AllowNVIDIAGPUScreens\"\n"
                "EndSection\n\n");

        fflush(file);
        return true;
    }

    return false;
}

static void remove_prime_outputclass(void) {
    char xorg_d_custom[PATH_MAX];
    snprintf(xorg_d_custom, sizeof(xorg_d_custom), "%s/11-nvidia-prime.conf",
            xorg_conf_d_path);
    fprintf(log_handle, "Removing %s\n", xorg_d_custom);
    unlink(xorg_d_custom);
}

static void remove_offload_serverlayout(void) {
    char xorg_d_custom[PATH_MAX];
    snprintf(xorg_d_custom, sizeof(xorg_d_custom), "%s/11-nvidia-offload.conf",
            xorg_conf_d_path);
    fprintf(log_handle, "Removing %s\n", xorg_d_custom);
    unlink(xorg_d_custom);
}

static bool manage_power_management(const struct device *device, bool enabled) {
    _cleanup_fclose_ FILE *file = NULL;
    char pci_device_path[PATH_MAX];

    snprintf(pci_device_path, sizeof(pci_device_path),
             "/sys/bus/pci/devices/%04x:%02x:%02x.%x/power/control",
             (unsigned int)device->domain,
             (unsigned int)device->bus,
             (unsigned int)device->dev,
             (unsigned int)device->func);

    fprintf(log_handle, "Setting power control to \"%s\" in %s\n", enabled ? "auto" : "on", pci_device_path);
    file = fopen(pci_device_path, "w");
    if (!file) {
        fprintf(log_handle, "Error while opening %s\n", pci_device_path);
        return false;
    }
    else {
        fputs(enabled ? "auto\n" : "on\n", file);

        fflush(file);
        return true;
    }
}

static void enable_power_management(const struct device *device) {
    manage_power_management(device, true);
}

static void disable_power_management(const struct device *device) {
    manage_power_management(device, false);
}

static bool unload_nvidia(void) {
    unload_module("nvidia-drm");
    unload_module("nvidia-uvm");
    unload_module("nvidia-modeset");

    return unload_module("nvidia");
}

static char* get_pid_by_name(const char *name) {
    char command[100];
    char *pid = NULL;

    snprintf(command, sizeof(command),
             "/bin/pidof %s",
             name);
    fprintf(log_handle, "Calling %s\n", command);
    pid = get_output(command, NULL, NULL);

    if (!pid) {
        fprintf(log_handle, "Info: no PID found for %s.\n",
                name);
        return NULL;
    }

    return pid;
}


static long get_uid_of_pid(const char *pid) {
    char path[PATH_MAX];

    _cleanup_free_ char *line = NULL;
    _cleanup_fclose_ FILE *file = NULL;
    size_t len = 0;
    size_t read;
    char pattern[] = "Uid:";
    long uid = -1;

    snprintf(path, sizeof(path),
             "/proc/%s/status",
             pid);
    fprintf(log_handle, "Opening %s\n", path);

    file = fopen(path, "r");
    if (file == NULL) {
        fprintf(log_handle, "Error: can't open %s\n", path);
        return -1;
    }
    while ((read = getline(&line, &len, file)) != -1) {
        if (istrstr(line, pattern) != NULL) {
            fprintf(log_handle, "found \"%s\"\n", line);
            if (strncmp(line, "Uid:", 4) == 0) {
                uid = strtol(line + 4, NULL, 10);
                fprintf(log_handle, "Found %ld\n", uid);
            }
        }
    }
    return uid;
}


static char* get_user_from_uid(const long uid) {
    size_t read;
    char *token, *str;
    char pattern[PATH_MAX];
    char *user = NULL;
    size_t len = 0;
    _cleanup_free_ char *line = NULL;
    _cleanup_fclose_ FILE *file = NULL;
    _cleanup_free_ char *tofree = NULL;

    snprintf(pattern, sizeof(pattern),
             "%ld",
             uid);
    fprintf(log_handle, "Looking for %s\n", pattern);

    file = fopen("/etc/passwd", "r");
    if (file == NULL)
         return NULL;
    while ((read = getline(&line, &len, file)) != -1 && (user == NULL)) {
        if (istrstr(line, pattern) != NULL) {
            tofree = str = strdup(line);
            /* Get the first result
             * gdm:x:120:125:Gnome Display Manager:/var/lib/gdm3:/bin/false
             */
            while( (token = strsep(&str, ":")) != NULL ) {
                user = strdup(token);
                fprintf(log_handle, "USER: %s\n", user);
                break;
            }
        }
    }
    return user;
}


/* Check a strings with pids, and find the gdm session */
static long find_pid_main_session(const char *pid_str) {
    _cleanup_free_ char *tofree = NULL;
    _cleanup_free_ char *user = NULL;
    long uid = -1;
    char *token, *str;
    long pid = -1;

    tofree = str = strdup(pid_str);
    while( (token = strsep(&str," ")) != NULL ) {
        if ( (uid = get_uid_of_pid(token)) >= 0) {
            fprintf(log_handle, "Found: %s %ld\n", token, uid);
            /*look up the UID in /etc/passwd */
            user = get_user_from_uid(uid);
            fprintf(log_handle, "User: %s UID: %ld\n", user, uid);
            if ((user != NULL) && (strcmp(user, "gdm") == 0)) {
                pid = strtol(token, NULL, 10);
                break;
            }
        }
    }
    return pid;
}


static long get_gdm_session_pid(const char* display_server) {
    _cleanup_free_ char *pid_str = NULL;
    long pid = -1;

    pid_str = get_pid_by_name(display_server);
    if (!pid_str) {
        fprintf(log_handle, "INFO: no PID found for %s.\n",
                display_server);
        return -1;
    }

    fprintf(log_handle, "INFO: found PID(s) %s for %s.\n",
                    pid_str, display_server);

    pid = find_pid_main_session(pid_str);

    fprintf(log_handle, "INFO: found PID %ld for Gdm main %s session.\n",
            pid, display_server);

    return pid;
}


/* Kill the main display session created by Gdm 3 */
static bool kill_main_display_session (void) {
    int i;
    _cleanup_free_ char *final_pid = NULL;
    char command[100];
    char server[] = "Xwayland";
    long pid = -1;
    int status = 0;
    /* try with Xwayland first */
    char *servers[2] = {"Xwayland", "Xorg"};

    if (!dry_run) {
        for(i = 0; i < 2; i++) {
            pid = get_gdm_session_pid(servers[i]);
            if (pid <= 0)
                fprintf(log_handle, "Info: no PID found for %s.\n", servers[i]);
            else
                break;
        }
        if (pid <= 0)
            return false;

        fprintf(log_handle, "Info: found PID(s) %ld for %s.\n",
                pid, server);

        /* Kill the session */
        snprintf(command, sizeof(command), "kill -KILL %ld", pid);
        fprintf(log_handle, "Calling %s\n", command);
        status = system(command);
    }
    return (status == 0);
}


static bool enable_prime(const char *prime_settings,
                        const struct device *device,
                        struct device **devices,
                        int cards_n) {
    bool status = false;
    int tries = 0;
    /* Check if prime_settings is available
     * File doesn't exist or empty
     */
    if (!exists_not_empty(prime_settings)) {
        fprintf(log_handle, "Warning: no settings for prime can be found in %s.\n",
                prime_settings);

       /* Try to create the file */
        if (!create_prime_settings(prime_settings)) {
            fprintf(log_handle, "Error: failed to create %s\n",
                    prime_settings);
            return false;
        }
    }

    get_prime_action();
    if (prime_mode == ON) {
        /* Create an OutputClass just for PRIME, to override
         * the default NVIDIA settings
         */
        create_prime_outputclass();
        /* Remove the ServerLayout */
        remove_offload_serverlayout();
        disable_power_management(device);
        if (!is_module_loaded("nvidia"))
            load_module("nvidia");
    }
    else if (prime_mode == ONDEMAND) {
        /* Create the ServerLayout required to enabling offload
         * for NVIDIA.
         */
        create_offload_serverlayout();
        /* Remove the OutputClass */
        remove_prime_outputclass();
        enable_power_management(device);
        if (!is_module_loaded("nvidia"))
            load_module("nvidia");
    }
    else {
        /* Remove the OutputClass and ServerLayout */
        remove_prime_outputclass();
        remove_offload_serverlayout();

unload_again:
        /* Unload the NVIDIA modules and enable pci power management */
        if (is_module_loaded("nvidia")) {
            status = unload_nvidia();

            if (!status && is_module_loaded("nvidia")) {
                fprintf(log_handle, "Warning: failure to unload the nvidia modules.\n");
                if (tries == 0) {
                    fprintf(log_handle, "Info: killing X...\n");
                    status = kill_main_display_session();
                    if (status) {
                        tries++;
                        goto unload_again;
                    }
                }
                else {
                    fprintf(log_handle, "Error: giving up on unloading nvidia...\n");
                    return false;
                }
            }
        }
        /* Set power control to "auto" to save power */
        enable_power_management(device);
    }

    return true;
}


int main(int argc, char *argv[]) {

    int opt, i;
    char *fake_lspci_file = NULL;
    char *new_boot_file = NULL;

    static int fake_offloading = 0;
    static int fake_module_available = 0;
    static int fake_module_versioned = 0;
    static int backup_log = 0;

    bool has_intel = false, has_amd = false, has_nvidia = false;
    bool has_changed = false;
    bool nvidia_loaded = false,
         intel_loaded = false, radeon_loaded = false,
         amdgpu_loaded = false, nouveau_loaded = false;
    bool nvidia_unloaded = false;
    bool nvidia_blacklisted = false,
         radeon_blacklisted = false, amdgpu_blacklisted = false,
         nouveau_blacklisted = false;
    bool nvidia_kmod_available = false,
         amdgpu_kmod_available = false;
    bool amdgpu_versioned = false;
    bool amdgpu_pro_px_installed = false;
    bool amdgpu_is_pro = false;
    int offloading = false;
    int status = 0;

    /* Vendor and device id (boot vga) */
    unsigned int boot_vga_vendor_id = 0, boot_vga_device_id = 0;

    /* The current number of cards */
    int cards_n = 0;

    /* The number of cards from last boot*/
    int last_cards_n = 0;

    /* Variables for pciaccess */
    int pci_init = -1;
    struct pci_device_iterator *iter = NULL;
    struct pci_device *info = NULL;

    /* Store the devices here */
    struct device *current_devices[MAX_CARDS_N];
    struct device *old_devices[MAX_CARDS_N];

    /* Device information (discrete) */
    struct device discrete_device = { 0 };


    while (1) {
        static struct option long_options[] =
        {
        /* These options set a flag. */
        {"dry-run", no_argument,     &dry_run, 1},
        {"fake-requires-offloading", no_argument, &fake_offloading, 1},
        {"fake-no-requires-offloading", no_argument, &fake_offloading, 0},
        {"fake-module-is-available", no_argument, &fake_module_available, 1},
        {"fake-module-is-not-available", no_argument, &fake_module_available, 0},
        {"backup-log", no_argument, &backup_log, 1},
        {"fake-module-is-versioned", no_argument, &fake_module_versioned, 1},
        /* These options don't set a flag.
          We distinguish them by their indices. */
        {"log",  required_argument, 0, 'l'},
        {"fake-lspci",  required_argument, 0, 'f'},
        {"last-boot-file", required_argument, 0, 'b'},
        {"new-boot-file", required_argument, 0, 'n'},
        {"fake-modules-path", required_argument, 0, 'm'},
        {"gpu-detection-path", required_argument, 0, 's'},
        {"prime-settings", required_argument, 0, 'z'},
        {"dmi-product-version-path", required_argument, 0, 'h'},
        {"dmi-product-name-path", required_argument, 0, 'i'},
        {"nvidia-driver-version-path", required_argument, 0, 'j'},
        {"modprobe-d-path", required_argument, 0, 'k'},
        {"xorg-conf-d-path", required_argument, 0, 'a'},
        {"amdgpu-pro-px-file", required_argument, 0, 'w'},
        {0, 0, 0, 0}
        };
        /* getopt_long stores the option index here. */
        int option_index = 0;

        opt = getopt_long (argc, argv, "a:b:c:d:f:g:h:i:j:k:l:m:n:o:p:q:r:s:t:x:y:z:w:",
                        long_options, &option_index);

        /* Detect the end of the options. */
        if (opt == -1)
         break;

        switch (opt) {
            case 0:
                if (long_options[option_index].flag != 0)
                    break;
                printf("option %s", long_options[option_index].name);
                if (optarg)
                    printf(" with arg %s", optarg);
                printf("\n");
                break;
            case 'a':
                xorg_conf_d_path = strdup(optarg);
                if (!xorg_conf_d_path)
                    abort();
                break;
            case 'l':
                /* printf("option -l with value '%s'\n", optarg); */
                log_file = malloc(strlen(optarg) + 1);
                if (log_file)
                    strcpy(log_file, optarg);
                else
                    abort();
                break;
            case 'b':
                /* printf("option -b with value '%s'\n", optarg); */
                last_boot_file = malloc(strlen(optarg) + 1);
                if (last_boot_file)
                    strcpy(last_boot_file, optarg);
                else
                    abort();
                break;
            case 'n':
                /* printf("option -n with value '%s'\n", optarg); */
                new_boot_file = malloc(strlen(optarg) + 1);
                if (new_boot_file)
                    strcpy(new_boot_file, optarg);
                else
                    abort();
                break;
            case 'f':
                /* printf("option -f with value '%s'\n", optarg); */
                fake_lspci_file = malloc(strlen(optarg) + 1);
                if (fake_lspci_file)
                    strcpy(fake_lspci_file, optarg);
                else
                    abort();
                break;
            case 'm':
                /* printf("option -m with value '%s'\n", optarg); */
                fake_modules_path = malloc(strlen(optarg) + 1);
                if (fake_modules_path)
                    strcpy(fake_modules_path, optarg);
                else
                    abort();
                break;
            case 's':
                /* printf("option -p with value '%s'\n", optarg); */
                gpu_detection_path = malloc(strlen(optarg) + 1);
                if (gpu_detection_path)
                    strcpy(gpu_detection_path, optarg);
                else
                    abort();
                break;
            case 'z':
                /* printf("option -p with value '%s'\n", optarg); */
                prime_settings = strdup(optarg);
                if (!prime_settings)
                    abort();
                break;
            case 'h':
                /* printf("option -p with value '%s'\n", optarg); */
                dmi_product_version_path = strdup(optarg);
                if (!dmi_product_version_path)
                    abort();
                break;
            case 'i':
                /* printf("option -p with value '%s'\n", optarg); */
                dmi_product_name_path = strdup(optarg);
                if (!dmi_product_name_path)
                    abort();
                break;
            case 'j':
                nvidia_driver_version_path = strdup(optarg);
                if (!nvidia_driver_version_path)
                    abort();
                break;
            case 'k':
                modprobe_d_path = strdup(optarg);
                if (!modprobe_d_path)
                    abort();
                break;
            case 'w':
                amdgpu_pro_px_file = strdup(optarg);
                if (!amdgpu_pro_px_file)
                    abort();
                break;
            case '?':
                /* getopt_long already printed an error message. */
                exit(1);
                break;

            default:
                abort();
        }

    }
    /*
    if (dry_run)
        printf("dry-run flag is set\n");
    */

    /* Send messages to the log or to stdout */
    if (log_file) {
        if (backup_log) {
            /* Move the old log away */
            move_log();
        }
        log_handle = fopen(log_file, "w");

        if (!log_handle) {
            /* Use stdout */
            log_handle = stdout;
            fprintf(log_handle, "Warning: writing to %s failed (%s)\n",
                    log_file, strerror(errno));
        }
    }
    else {
        log_handle = stdout;
    }

    if (is_disabled_in_cmdline()) {
        fprintf(log_handle, "Disabled by kernel parameter \"%s\"\n",
                KERN_PARAM);
        goto end;
    }


    /* TODO: require arguments and abort if they're not available */

    if (log_file)
        fprintf(log_handle, "log_file: %s\n", log_file);

    if (!last_boot_file)
        last_boot_file = strdup(LAST_BOOT);

    if (last_boot_file)
        fprintf(log_handle, "last_boot_file: %s\n", last_boot_file);
    else {
        fprintf(log_handle, "No last_boot_file!\n");
        goto end;
    }

    if (!new_boot_file)
        new_boot_file = strdup(last_boot_file);
    fprintf(log_handle, "new_boot_file: %s\n", new_boot_file);

    if (fake_lspci_file)
        fprintf(log_handle, "fake_lspci_file: %s\n", fake_lspci_file);

    if (!gpu_detection_path)
        gpu_detection_path = strdup("/run");

    if (prime_settings)
        fprintf(log_handle, "prime_settings file: %s\n", prime_settings);
    else {
        prime_settings = strdup("/etc/prime-discrete");
        if (!prime_settings) {
            fprintf(log_handle, "Couldn't allocate prime_settings\n");
            goto end;
        }
    }

    if (dmi_product_name_path)
        fprintf(log_handle, "dmi_product_name_path file: %s\n", dmi_product_name_path);
    else {
        dmi_product_name_path = strdup("/sys/class/dmi/id/product_name");
        if (!dmi_product_name_path) {
            fprintf(log_handle, "Couldn't allocate dmi_product_name_path\n");
            goto end;
        }
    }

    if (dmi_product_version_path)
        fprintf(log_handle, "dmi_product_version_path file: %s\n", dmi_product_version_path);
    else {
        dmi_product_version_path = strdup("/sys/class/dmi/id/product_version");
        if (!dmi_product_version_path) {
            fprintf(log_handle, "Couldn't allocate dmi_product_version_path\n");
            goto end;
        }
    }

    if (nvidia_driver_version_path)
        fprintf(log_handle, "nvidia_driver_version_path file: %s\n", nvidia_driver_version_path);
    else {
        nvidia_driver_version_path = strdup("/sys/module/nvidia/version");
        if (!nvidia_driver_version_path) {
            fprintf(log_handle, "Couldn't allocate nvidia_driver_version_path\n");
            goto end;
        }
    }

    if (amdgpu_pro_px_file)
        fprintf(log_handle, "amdgpu_pro_px_file file: %s\n", amdgpu_pro_px_file);
    else {
        amdgpu_pro_px_file = strdup(AMDGPU_PRO_PX);
        if (!amdgpu_pro_px_file) {
            fprintf(log_handle, "Couldn't allocate amdgpu_pro_px_file\n");
            goto end;
        }
    }

    if (modprobe_d_path)
        fprintf(log_handle, "modprobe_d_path file: %s\n", modprobe_d_path);
    else {
        modprobe_d_path = strdup("/etc/modprobe.d");
        if (!modprobe_d_path) {
            fprintf(log_handle, "Couldn't allocate modprobe_d_path\n");
            goto end;
        }
    }

    if (xorg_conf_d_path)
        fprintf(log_handle, "xorg_conf_d_path file: %s\n", xorg_conf_d_path);
    else {
        xorg_conf_d_path = strdup("/usr/share/X11/xorg.conf.d");
        if (!xorg_conf_d_path) {
            fprintf(log_handle, "Couldn't allocate xorg_conf_d_path\n");
            goto end;
        }
    }

    if (fake_modules_path)
        fprintf(log_handle, "fake_modules_path file: %s\n", fake_modules_path);

    nvidia_loaded = is_module_loaded("nvidia");
    nvidia_unloaded = nvidia_loaded ? false : has_unloaded_module("nvidia");
    nvidia_blacklisted = is_module_blacklisted("nvidia");
    intel_loaded = is_module_loaded("i915") || is_module_loaded("i810");
    radeon_loaded = is_module_loaded("radeon");
    radeon_blacklisted = is_module_blacklisted("radeon");
    amdgpu_loaded = is_module_loaded("amdgpu");
    amdgpu_blacklisted = is_module_blacklisted("amdgpu");
    amdgpu_versioned = is_module_versioned("amdgpu");
    amdgpu_pro_px_installed = exists_not_empty(amdgpu_pro_px_file);
    nouveau_loaded = is_module_loaded("nouveau");
    nouveau_blacklisted = is_module_blacklisted("nouveau");


    if (fake_lspci_file) {
        nvidia_kmod_available = fake_module_available;
        amdgpu_kmod_available = fake_module_available;
        amdgpu_versioned = fake_module_versioned ? true : false;
    }
    else {
        nvidia_kmod_available = is_module_available("nvidia");
        amdgpu_kmod_available = is_module_available("amdgpu");
    }

    amdgpu_is_pro = amdgpu_kmod_available && amdgpu_versioned;

    fprintf(log_handle, "Is nvidia loaded? %s\n", (nvidia_loaded ? "yes" : "no"));
    fprintf(log_handle, "Was nvidia unloaded? %s\n", (nvidia_unloaded ? "yes" : "no"));
    fprintf(log_handle, "Is nvidia blacklisted? %s\n", (nvidia_blacklisted ? "yes" : "no"));
    fprintf(log_handle, "Is intel loaded? %s\n", (intel_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is radeon loaded? %s\n", (radeon_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is radeon blacklisted? %s\n", (radeon_blacklisted ? "yes" : "no"));
    fprintf(log_handle, "Is amdgpu loaded? %s\n", (amdgpu_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is amdgpu blacklisted? %s\n", (amdgpu_blacklisted ? "yes" : "no"));
    fprintf(log_handle, "Is amdgpu versioned? %s\n", (amdgpu_versioned ? "yes" : "no"));
    fprintf(log_handle, "Is amdgpu pro stack? %s\n", (amdgpu_is_pro ? "yes" : "no"));
    fprintf(log_handle, "Is nouveau loaded? %s\n", (nouveau_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is nouveau blacklisted? %s\n", (nouveau_blacklisted ? "yes" : "no"));
    fprintf(log_handle, "Is nvidia kernel module available? %s\n", (nvidia_kmod_available ? "yes" : "no"));
    fprintf(log_handle, "Is amdgpu kernel module available? %s\n", (amdgpu_kmod_available ? "yes" : "no"));

    /* Get the driver to use for intel in an optimus system */
    prime_intel_driver = get_prime_intel_driver();

    if (fake_lspci_file) {
        /* Get the current system data from a file */
        status = read_data_from_file(current_devices, &cards_n,
                                     fake_lspci_file);
        if (!status) {
            fprintf(log_handle, "Error: can't read %s\n", fake_lspci_file);
            goto end;
        }
        /* Set data in the devices structs */
        for(i = 0; i < cards_n; i++) {
            if (current_devices[i]->vendor_id == NVIDIA) {
                has_nvidia = true;
            }
            else if (current_devices[i]->vendor_id == AMD) {
                has_amd = true;
            }
            else if (current_devices[i]->vendor_id == INTEL) {
                has_intel = true;
            }
            /* Set unavailable fake outputs */
            current_devices[i]->has_connected_outputs = -1;
        }
        /* Set fake offloading */
        offloading = fake_offloading;
    }
    else {
        /* Get the current system data */
        pci_init = pci_system_init();
        if (pci_init != 0)
            goto end;

        iter = pci_slot_match_iterator_create(&match);
        if (!iter)
            goto end;

        while ((info = pci_device_next(iter)) != NULL) {
            if (PCIINFOCLASSES(info->device_class)) {
                fprintf(log_handle, "Vendor/Device Id: %x:%x\n", info->vendor_id, info->device_id);
                fprintf(log_handle, "BusID \"PCI:%d@%d:%d:%d\"\n",
                        (int)info->bus, (int)info->domain, (int)info->dev, (int)info->func);
                fprintf(log_handle, "Is boot vga? %s\n", (pci_device_is_boot_vga(info) ? "yes" : "no"));

                if (!is_device_bound_to_driver(info)) {
                    fprintf(log_handle, "The device is not bound to any driver.\n");
                }

                if (is_device_pci_passthrough(info)) {
                    fprintf(log_handle, "The device is a pci passthrough. Skipping...\n");
                    continue;
                }

                /* char *driver = NULL; */
                if (info->vendor_id == NVIDIA) {
                    has_nvidia = true;
                }
                else if (info->vendor_id == INTEL) {
                    has_intel = true;
                }
                else if (info->vendor_id == AMD) {
                    has_amd = true;
                }

                /* We don't support more than MAX_CARDS_N */
                if (cards_n < MAX_CARDS_N) {
                    current_devices[cards_n] = malloc(sizeof(struct device));
                    if (!current_devices[cards_n])
                        goto end;
                    current_devices[cards_n]->boot_vga = pci_device_is_boot_vga(info);
                    current_devices[cards_n]->vendor_id = info->vendor_id;
                    current_devices[cards_n]->device_id = info->device_id;
                    current_devices[cards_n]->domain = info->domain;
                    current_devices[cards_n]->bus = info->bus;
                    current_devices[cards_n]->dev = info->dev;
                    current_devices[cards_n]->func = info->func;
                }
                else {
                    fprintf(log_handle, "Warning: too many devices %d. "
                                        "Max supported %d. Ignoring the rest.\n",
                                        cards_n, MAX_CARDS_N);
                    break;
                }
                /*
                else {
                    fprintf(stderr, "No hybrid graphics cards detected\n");
                    break;
                }
                */
                cards_n++;
            }
        }
        /* Add information about connected outputs */
        add_connected_outputs_info(current_devices, cards_n);

        /* See if it requires RandR offloading */
        offloading = requires_offloading(current_devices, cards_n);
    }

    fprintf(log_handle, "Does it require offloading? %s\n", (offloading ? "yes" : "no"));

    /* Remove a file that will tell other apps such as
     * nvidia-prime if we need to offload rendering.
     */
    if (!offloading && !dry_run)
        unlink(OFFLOADING_CONF);


    /* Read the data from last boot */
    status = read_data_from_file(old_devices, &last_cards_n,
                                 last_boot_file);
    if (!status) {
        fprintf(log_handle, "Can't read %s\n", last_boot_file);
        goto end;
    }

    fprintf(log_handle, "last cards number = %d\n", last_cards_n);

    /* Write the current data */
    status = write_data_to_file(current_devices,
                                cards_n,
                                new_boot_file);
    if (!status) {
        fprintf(log_handle, "Error: can't write to %s\n", last_boot_file);
        goto end;
    }

    fprintf(log_handle, "Has amd? %s\n", (has_amd ? "yes" : "no"));
    fprintf(log_handle, "Has intel? %s\n", (has_intel ? "yes" : "no"));
    fprintf(log_handle, "Has nvidia? %s\n", (has_nvidia ? "yes" : "no"));
    fprintf(log_handle, "How many cards? %d\n", cards_n);

    /* See if the system has changed */
    has_changed = has_system_changed(old_devices,
                                     current_devices,
                                     last_cards_n,
                                     cards_n);
    fprintf(log_handle, "Has the system changed? %s\n", has_changed ? "Yes" : "No");

    if (has_changed)
        fprintf(log_handle, "System configuration has changed\n");

    if (cards_n == 1) {
        fprintf(log_handle, "Single card detected\n");

        /* Get data about the boot_vga card */
        get_boot_vga(current_devices, cards_n,
                     &boot_vga_vendor_id,
                     &boot_vga_device_id);

        if (boot_vga_vendor_id == INTEL) {
            if (offloading && nvidia_unloaded) {
                /* NVIDIA PRIME */
                fprintf(log_handle, "PRIME detected\n");

                /* Get the details of the disabled discrete from a file */
                find_disabled_cards(gpu_detection_path, current_devices,
                                    &cards_n, add_gpu_from_file);

                /* Get data about the first discrete card */
                get_first_discrete(current_devices, cards_n,
                                   &discrete_device);

                /* Try to enable prime */
                if (enable_prime(prime_settings,
                                 &discrete_device, current_devices, cards_n)) {

                    /* Write permanent settings about offloading */
                    set_offloading();
                }
                goto end;
            }
            else {
                fprintf(log_handle, "Nothing to do\n");
                }
            }
        else if (boot_vga_vendor_id == AMD) {
            if (has_changed && amdgpu_loaded && amdgpu_is_pro && amdgpu_pro_px_installed) {
                /* If amdgpu-pro-px exists, we can assume it's a pxpress system. But now the
                 * system has one card only, user probably disabled Switchable Graphics in
                 * BIOS. So we need to use discrete config file here.
                 */
                fprintf(log_handle, "AMDGPU-Pro discrete graphics detected\n");

                run_amdgpu_pro_px(RESET);
            }
            else {
                fprintf(log_handle, "Nothing to do\n");
            }
        }
        else if (boot_vga_vendor_id == NVIDIA) {
            fprintf(log_handle, "Nothing to do\n");
        }
    }
    else if (cards_n > 1) {
        /* Get data about the boot_vga card */
        get_boot_vga(current_devices, cards_n,
                     &boot_vga_vendor_id,
                     &boot_vga_device_id);

        /* Get data about the first discrete card */
        get_first_discrete(current_devices, cards_n,
                           &discrete_device);

        /* Intel + another GPU */
        if (boot_vga_vendor_id == INTEL) {
            fprintf(log_handle, "Intel IGP detected\n");
            /* AMDGPU-Pro Switchable */
            if (has_changed && amdgpu_loaded && amdgpu_is_pro && amdgpu_pro_px_installed) {
                /* Similar to switchable enabled -> disabled case, but this time
                 * to deal with switchable disabled -> enabled change.
                 */
                fprintf(log_handle, "AMDGPU-Pro switchable graphics detected\n");

                run_amdgpu_pro_px(MODE_POWERSAVING);
            }
            /* NVIDIA Optimus */
            else if (offloading && (intel_loaded && !nouveau_loaded &&
                                 (nvidia_loaded || nvidia_kmod_available))) {
                fprintf(log_handle, "Intel hybrid system\n");

                /* Try to enable prime */
                if (enable_prime(prime_settings,
                             &discrete_device, current_devices, cards_n)) {

                    /* Write permanent settings about offloading */
                    set_offloading();
                }
                else {
                    fprintf(log_handle, "Nothing to do\n");
                }

                goto end;
            }
            else {
                /* Desktop system or Laptop with open drivers only */
                fprintf(log_handle, "Desktop system detected\n");
                fprintf(log_handle, "or laptop with open drivers\n");
                fprintf(log_handle, "Nothing to do\n");
            }
        }
        else {
                fprintf(log_handle, "Unsupported discrete card vendor: %x\n", discrete_device.vendor_id);
                fprintf(log_handle, "Nothing to do\n");
        }
    }




end:
    if (pci_init == 0)
        pci_system_cleanup();

    if (iter)
        free(iter);

    if (log_file)
        free(log_file);

    if (last_boot_file)
        free(last_boot_file);

    if (new_boot_file)
        free(new_boot_file);

    if (fake_lspci_file)
        free(fake_lspci_file);

    if (gpu_detection_path)
        free(gpu_detection_path);

    if (fake_modules_path)
        free(fake_modules_path);

    if (prime_settings)
        free(prime_settings);

    if (dmi_product_name_path)
        free(dmi_product_name_path);

    if (dmi_product_version_path)
        free(dmi_product_version_path);

    if (nvidia_driver_version_path)
        free(nvidia_driver_version_path);

    if (modprobe_d_path)
        free(modprobe_d_path);

    if (xorg_conf_d_path)
        free(xorg_conf_d_path);

    /* Free the devices structs */
    for(i = 0; i < cards_n; i++) {
        free(current_devices[i]);
    }

    for(i = 0; i < last_cards_n; i++) {
        free(old_devices[i]);
    }

    /* Flush and close the log */
    if (log_handle != stdout) {
        fflush(log_handle);
        fclose(log_handle);
    }

    return 0;
}
