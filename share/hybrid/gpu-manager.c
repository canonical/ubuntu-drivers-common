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
#include <ctype.h>
#include <pciaccess.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <dirent.h>
#include <getopt.h>
#include <time.h>
#include <fcntl.h>
#include "xf86drm.h"
#include "xf86drmMode.h"

#define PCI_CLASS_DISPLAY               0x03
#define PCI_CLASS_DISPLAY_OTHER         0x0380

#define PCIINFOCLASSES(c) \
    ( (((c) & 0x00ff0000) \
     == (PCI_CLASS_DISPLAY << 16)) )

#define LAST_BOOT "/var/lib/ubuntu-drivers-common/last_gfx_boot"
#define OFFLOADING_CONF "/var/lib/ubuntu-drivers-common/requires_offloading"
#define XORG_CONF "/etc/X11/xorg.conf"
#define KERN_PARAM "nogpumanager"

#define AMD 0x1002
#define INTEL 0x8086
#define NVIDIA 0x10de

#define MAX_CARDS_N 10

static char *log_file = NULL;
static FILE *log_handle = NULL;
static char *last_boot_file = NULL;
static char *xorg_conf_file = NULL;
static char *amd_pcsdb_file = NULL;
static int dry_run = 0;
static int fake_lightdm = 0;
static char *fake_modules_path = NULL;
static char *fake_alternatives_path = NULL;
static char *fake_dmesg_path = NULL;
static char *prime_settings = NULL;
static char *bbswitch_path = NULL;
static char *bbswitch_quirks_path = NULL;
static char *dmi_product_version_path = NULL;
static char *main_arch_path = NULL;
static char *other_arch_path = NULL;


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
};


struct alternatives {
    /* These are just to
     *  detect the installer
     */
    int nvidia_available;
    int fglrx_available;
    int mesa_available;
    int pxpress_available;
    int prime_available;

    /* The ones that may be enabled */
    int nvidia_enabled;
    int fglrx_enabled;
    int mesa_enabled;
    int pxpress_enabled;
    int prime_enabled;

    char *current;
};


/* Case insensitive equivalent of strstr */
static const char *istrstr(const char *str1, const char *str2)
{
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


static int exists_not_empty(const char *file) {
    struct stat stbuf;

    /* If file doesn't exist */
    if (stat(file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", file);
        return 0;
    }
    /* If file is empty */
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size) {
        fprintf(log_handle, "%s is empty\n", file);
        return 0;
    }
    return 1;
}


/* Get parameters we may need to pass to bbswitch */
static char * get_params_from_quirks() {
    char *dmi_product_version = NULL;
    FILE *file;
    char *params = NULL;
    char line[1035];
    size_t len = 0;
    char *tok;

    if (!exists_not_empty(dmi_product_version_path)) {
        fprintf(log_handle, "Error: %s does not exist or is empty.\n", dmi_product_version_path);
    }

    if (!exists_not_empty(bbswitch_quirks_path)) {
        fprintf(log_handle, "Error: %s does not exist or is empty.\n", bbswitch_quirks_path);
    }

    /* get dmi product version */
    file = fopen(dmi_product_version_path, "r");
    if (file == NULL) {
        fprintf(log_handle, "can't open %s\n", dmi_product_version_path);
        return NULL;
    }
    if (getline(&dmi_product_version, &len, file) == -1) {
        fprintf(log_handle, "can't get line from %s\n", dmi_product_version_path);
        return NULL;
    }
    fclose(file);

    if (dmi_product_version) {
        /* Remove newline */
        len = strlen(dmi_product_version);
        if(dmi_product_version[len-1] == '\n' )
           dmi_product_version[len-1] = 0;

        /* Look for zero-length dmi_product_version */
        if (strlen(dmi_product_version) == 0) {
            fprintf(log_handle, "Invalid dmi_product_version=\"%s\"\n",
                    dmi_product_version);

            free(dmi_product_version);
            return params;
        }

        fprintf(log_handle, "dmi_product_version=\"%s\"\n", dmi_product_version);

        file = fopen(bbswitch_quirks_path, "r");
        if (file == NULL) {
            fprintf(log_handle, "can't open %s\n", bbswitch_quirks_path);
            free(dmi_product_version);
            return NULL;
        }

        while (fgets(line, sizeof(line), file)) {
            /* Ignore comments */
            if (strstr(line, "#") != NULL) {
                continue;
            }

            if (istrstr(line, dmi_product_version) != NULL) {
                fprintf(log_handle, "Found matching quirk\n");

                tok = strtok(line, "\"");

                while (tok != NULL)
                {
                    tok = strtok (NULL, "\"");
                    if (tok && (isspace(tok[0]) == 0)) {
                        params = strdup(tok);
                        break;
                    }
                }
                break;
            }
        }
        fclose(file);

        free(dmi_product_version);
    }

    return params;
}


static int act_upon_module_with_params(const char *module,
                                       int mode,
                                       char *params) {
    int status = 0;
    char command[300];

    fprintf(log_handle, "%s %s with \"%s\" parameters\n",
            mode ? "Loading" : "Unloading",
            module, params ? params : "no");

    if (params) {
        sprintf(command, "%s %s %s", mode ? "/sbin/modprobe" : "/sbin/rmmod",
                module, params);
        free(params);
    }
    else {
        sprintf(command, "%s %s", mode ? "/sbin/modprobe" : "/sbin/rmmod",
                module);
    }

    if (dry_run)
        return 1;

    status = system(command);

    return (status == 0);
}

/* Load a kernel module and pass it parameters */
static int load_module_with_params(const char *module,
                                   char *params) {
    return (act_upon_module_with_params(module, 1, params));
}


/* Load a kernel module */
static int load_module(const char *module) {
    return (load_module_with_params(module, NULL));
}


/* Unload a kernel module */
static int unload_module(const char *module) {
    return (act_upon_module_with_params(module, 0, NULL));
}


/* Load bbswitch and pass some parameters */
static int load_bbswitch() {
    char *params = NULL;
    char *temp_params = NULL;
    char basic[] = "load_state=-1 unload_state=1";

    temp_params = get_params_from_quirks();
    if (!temp_params) {
        params = strdup(basic);
    }
    else {
        params = malloc(strlen(temp_params) + strlen(basic) + 2);
        if (!params)
            return 0;
        strcpy(params, basic);
        strcat(params, " ");
        strcat(params, temp_params);

        free(temp_params);
    }


    return (load_module_with_params("bbswitch", params));
}


/* Get the first match from the output of a command */
static char* get_output(char *command, char *pattern, char *ignore) {
    int len;
    char buffer[1035];
    char *output = NULL;
    FILE *pfile = NULL;
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
    pclose(pfile);

    if (output) {
        /* Remove newline */
        len = strlen(output);
        if(output[len-1] == '\n' )
           output[len-1] = 0;
    }
    return output;
}


static void get_architecture_paths(char **main_arch_path,
                                  char **other_arch_path) {
    char *main_arch = NULL;

    main_arch = get_output("dpkg --print-architecture", NULL, NULL);
    if (strcmp(main_arch, "amd64") == 0) {
        *main_arch_path = strdup("x86_64-linux-gnu");
        *other_arch_path = strdup("i386-linux-gnu");
    }
    else if (strcmp(main_arch, "i386") == 0) {
        *main_arch_path = strdup("i386-linux-gnu");
        *other_arch_path = strdup("x86_64-linux-gnu");
    }
    free(main_arch);
}


/* Get the master link of an alternative */
static char* get_alternative_link(char *arch_path, char *pattern) {
    char *alternative = NULL;
    char command[300];
    FILE *pfile = NULL;

    if (dry_run && fake_alternatives_path) {
        pfile = fopen(fake_alternatives_path, "r");
        if (pfile == NULL) {
            fprintf(stderr, "I couldn't open %s for reading.\n",
                    fake_alternatives_path);
            return NULL;
        }
        while (fgets(command, sizeof(command), pfile)) {
            /* Make sure we don't catch prime by mistake when
             * looking for nvidia
             */
            if (strcmp(pattern, "nvidia") == 0) {
                if (strstr(command, pattern) != NULL) {
                    alternative = strdup(command);
                    break;
                }
            }
            else {
                if (strstr(command, pattern) != NULL) {
                alternative = strdup(command);
                break;
                }
            }
        }
        fclose(pfile);
    }
    else {
        sprintf(command, "update-alternatives --list %s_gl_conf",
                arch_path);

        /* Make sure we don't catch prime by mistake when
         * looking for nvidia
         */
        if (strcmp(pattern, "nvidia") == 0)
            alternative = get_output(command, pattern, "prime");
        else
            alternative = get_output(command, pattern, NULL);
    }

    return alternative;
}


/* Look for unloaded modules in dmesg */
static int has_unloaded_module(char *module) {
    int status = 0;
    char command[100];

    if (dry_run && fake_dmesg_path) {
        /* Make sure the file exists and is not empty */
        if (!exists_not_empty(fake_dmesg_path)) {
            return 0;
        }

        sprintf(command, "grep -q \"%s: module\" %s",
                module, fake_dmesg_path);
        status = system(command);
        fprintf(log_handle, "grep fake dmesg status %d\n", status);
    }
    else {
        sprintf(command, "dmesg | grep -q \"%s: module\"",
                module);
        status = system(command);
        fprintf(log_handle, "grep dmesg status %d\n", status);
    }

    fprintf(log_handle, "dmesg status %d == 0? %s\n", status, (status == 0) ? "Yes" : "No");

    return (status == 0);
}


static int find_string_in_file(const char *path, const char *pattern) {
    FILE *pfile = NULL;
    char  *line = NULL;
    size_t len = 0;
    size_t read;

    int found = 0;

    pfile = fopen(path, "r");
    if (pfile == NULL)
         return found;
    while ((read = getline(&line, &len, pfile)) != -1) {
        if (istrstr(line, pattern) != NULL) {
            found = 1;
            break;
        }
    }
    fclose(pfile);
    if (line)
        free(line);

    return found;
}


/* Check if lightdm is the default login manager */
static int is_lightdm_default() {
    if (dry_run)
        return fake_lightdm;

    return (find_string_in_file("/etc/X11/default-display-manager",
            "lightdm"));
}


static void detect_available_alternatives(struct alternatives *info, char *pattern) {
    if (strstr(pattern, "mesa")) {
        info->mesa_available = 1;
    }
    else if (strstr(pattern, "fglrx")) {
        info->fglrx_available = 1;
    }
    else if (strstr(pattern, "pxpress")) {
        info->pxpress_available = 1;
    }
    else if (strstr(pattern, "nvidia")) {
        if (strstr(pattern, "prime") != NULL) {
            info->prime_available = 1;
        }
        else {
            info->nvidia_available = 1;
        }
    }
}

static void detect_enabled_alternatives(struct alternatives *info) {
    if (strstr(info->current, "mesa") != NULL) {
        info->mesa_enabled = 1;
    }
    else if (strstr(info->current, "fglrx") != NULL) {
        info->fglrx_enabled = 1;
    }
    else if (strstr(info->current, "pxpress") != NULL) {
        info->pxpress_enabled = 1;
    }
    else if (strstr(info->current, "nvidia") != NULL) {
        if (strstr(info->current, "prime") != NULL) {
            info->prime_enabled = 1;
        }
        else {
            info->nvidia_enabled = 1;
        }
    }
}


static int get_alternatives(struct alternatives *info, const char *master_link) {
    int len;
    char command[200];
    char buffer[1035];
    FILE *pfile = NULL;
    char *value = NULL;
    char *other = NULL;
    const char ch = '/';

    /* Test */
    if (fake_alternatives_path) {
        pfile = fopen(fake_alternatives_path, "r");
        /* Set the enabled alternatives in the struct */
        detect_enabled_alternatives(info);
    }
    else {
        sprintf(command, "/usr/bin/update-alternatives --query %s_gl_conf", master_link);

        pfile = popen(command, "r");
        if (pfile == NULL) {
            fprintf(stderr, "Failed to run command: %s\n", command);
            return 0;
        }
    }

    while (fgets(buffer, sizeof(buffer), pfile) != NULL) {
        if (strstr(buffer, "Value:")) {
            value = strchr(buffer, ch);
            if (value != NULL) {
                /* If info->current is not NULL, then it's a fake
                 * alternative, which we won't override
                 */
                if (!info->current) {
                    info->current = strdup(value);
                    /* Remove newline */
                    len = strlen(info->current);
                    if(info->current[len-1] == '\n' )
                       info->current[len-1] = 0;
                }
                /* Set the enabled alternatives in the struct */
                detect_enabled_alternatives(info);
            }

        }
        else if (strstr(buffer, "Alternative:") || fake_alternatives_path) {
            other = strchr(buffer, ch);
            if (other != NULL) {
                /* Set the available alternatives in the struct */
                detect_available_alternatives(info, other);
            }


        }
    }

    pclose(pfile);

    return 1;
}


/* Get the master link of an alternative */
static int set_alternative(char *arch_path, char *alternative) {
    int status = -1;
    char command[200];
    sprintf(command, "/usr/bin/update-alternatives --set %s_gl_conf %s",
            arch_path, alternative);

    if (dry_run) {
        status = 1;
        fprintf(log_handle, "%s\n", command);
    }
    else {
        fprintf(log_handle, "%s\n", command);
        status = system(command);
        fprintf(log_handle, "update-alternatives status %d\n", status);
    }

    if (status == -1)
        return 0;

    /* call ldconfig */
    if (dry_run) {
        fprintf(log_handle, "Calling ldconfig\n");
    }
    else {
        fprintf(log_handle, "Calling ldconfig\n");
        status = system("/sbin/ldconfig");
        fprintf(log_handle, "ldconfig status %d\n", status);
    }

    if (status == -1)
        return 0;
    return 1;
}

static int select_driver(char *driver) {
    int status = 0;
    char *alternative = NULL;
    alternative = get_alternative_link(main_arch_path, driver);

    if (alternative == NULL) {
        fprintf(log_handle, "Error: no alternative found for %s\n", driver);
    }
    else {
        /* Set the alternative */
        status = set_alternative(main_arch_path, alternative);

        /* Only for amd64 */
        if (status && strcmp(main_arch_path, "x86_64-linux-gnu") == 0) {
            /* Free the alternative */
            free(alternative);
            alternative = NULL;

            /* Try to get the alternative for the other architecture */
            alternative = get_alternative_link(other_arch_path, driver);
            if (alternative) {
                /* No need to check its status */
                set_alternative(other_arch_path, alternative);

                /* Free the alternative */
                free(alternative);
            }
        }
        else {
            /* Free the alternative */
            free(alternative);
        }
    }
    return status;
}


static int is_file_empty(const char *file) {
    struct stat stbuf;

    if (stat(file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", file);
        return 0;
    }
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size)
        return 1;

    return 0;
}


static int has_cmdline_option(const char *option)
{
    return (find_string_in_file("/proc/cmdline", option));
}


static int is_disabled_in_cmdline() {
    return has_cmdline_option(KERN_PARAM);
}

/* This is just for writing the BusID of the discrete
 * card
 */
static int write_to_xorg_conf(struct device **devices, int cards_n,
                              unsigned int vendor_id) {
    int i;
    FILE *pfile = NULL;

    fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);

    pfile = fopen(xorg_conf_file, "w");
    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                xorg_conf_file);
        return 0;
    }


    for(i = 0; i < cards_n; i++) {
        if (devices[i]->vendor_id == vendor_id) {
            fprintf(pfile,
               "Section \"Device\"\n"
               "    Identifier \"Default Card %d\"\n"
               "    BusID \"PCI:%d@%d:%d:%d\"\n"
               "EndSection\n\n",
               i,
               (int)(devices[i]->bus),
               (int)(devices[i]->domain),
               (int)(devices[i]->dev),
               (int)(devices[i]->func));
        }
    }

    fflush(pfile);
    fclose(pfile);
    return 1;
}


static int write_pxpress_xorg_conf(struct device **devices, int cards_n) {
    int i;
    FILE *pfile = NULL;

    fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);

    pfile = fopen(xorg_conf_file, "w");
    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                xorg_conf_file);
        return 0;
    }

    fprintf(pfile,
            "Section \"ServerLayout\"\n"
            "    Identifier \"amd-layout\"\n"
            "    Screen 0 \"amd-screen\" 0 0\n"
            "EndSection\n\n");

    for(i = 0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL) {
            fprintf(pfile,
                "Section \"Device\"\n"
                "    Identifier \"intel\"\n"
                "    Driver \"intel\"\n"
                "    Option \"AccelMethod\" \"uxa\"\n"
                "    BusID \"PCI:%d@%d:%d:%d\"\n"
                "EndSection\n\n",
                (int)(devices[i]->bus),
                (int)(devices[i]->domain),
                (int)(devices[i]->dev),
                (int)(devices[i]->func));
        }
        else if (devices[i]->vendor_id == AMD) {
            /* FIXME: fglrx doesn't seem to support
             *        the domain, so we only use
             *        bus, dev, and func
             */
            fprintf(pfile,
                "Section \"Device\"\n"
                "    Identifier \"amd-device\"\n"
                "    Driver \"fglrx\"\n"
                /*"    BusID \"PCI:%d@%d:%d:%d\"\n" */
                "    BusID \"PCI:%d:%d:%d\"\n"
                "EndSection\n\n"
                "Section \"Monitor\"\n"
                "    Identifier \"amd-monitor\"\n"
                "    Option \"VendorName\" \"ATI Proprietary Driver\"\n"
                "    Option \"ModelName\" \"Generic Autodetecting Monitor\"\n"
                "    Option \"DPMS\" \"true\"\n"
                "EndSection\n\n"
                "Section \"Screen\"\n"
                "    Identifier \"amd-screen\"\n"
                "    Device \"amd-device\"\n"
                "    Monitor \"amd-monitor\"\n"
                "    DefaultDepth 24\n"
                "    SubSection \"Display\"\n"
                "        Viewport   0 0\n"
                "        Depth     24\n"
                "    EndSubSection\n"
                "EndSection\n\n",
                (int)(devices[i]->bus),
                /* (int)(devices[i]->domain), */
                (int)(devices[i]->dev),
                (int)(devices[i]->func));
        }
    }

    fflush(pfile);
    fclose(pfile);
    return 1;
}


/* Check AMD's configuration file is the discrete GPU
 * is set to be disabled
 */
static int is_pxpress_dgpu_disabled() {
    int disabled = 0;
    /* We don't need a huge buffer */
    char line[100];
    FILE *file;

    if (!exists_not_empty(amd_pcsdb_file))
        return 0;

    file = fopen(amd_pcsdb_file, "r");

    if (!file) {
        fprintf(log_handle, "Error: I couldn't open %s for reading.\n",
                amd_pcsdb_file);
        return 0;
    }


    while (fgets(line, sizeof(line), file)) {
        /* This means that a GPU has to be disabled */
        if (istrstr(line, "PX_GPUDOWN=") != NULL) {
            disabled = 1;
            break;
        }
    }

    fclose(file);

    return disabled;
}


/* Check if binary drivers are still set in xorg.conf */
static int has_xorg_conf_binary_drivers(struct device **devices,
                                 int cards_n) {
    int found_binary = 0;
    char line[2048];
    FILE *file;

    if (!exists_not_empty(xorg_conf_file))
        return 0;

    file = fopen(xorg_conf_file, "r");

    if (!file) {
        fprintf(log_handle, "Error: I couldn't open %s for reading.\n",
                xorg_conf_file);
        return 0;
    }

    while (fgets(line, sizeof(line), file)) {
        /* Ignore comments */
        if (strstr(line, "#") == NULL) {
            /* Parse drivers here */
            if (istrstr(line, "Driver") != NULL) {
                if ((istrstr(line, "fglrx") != NULL) || (istrstr(line, "nvidia") != NULL)) {
                    found_binary = 1;
                    fprintf(log_handle, "Found binary driver in %s\n", xorg_conf_file);
                    break;
                }
            }
        }
    }

    fclose(file);

    return found_binary;
}


/* Check xorg.conf to see if it's all properly set */
static int check_prime_xorg_conf(struct device **devices,
                                 int cards_n) {
    int i;
    int intel_matches = 0;
    int nvidia_matches = 0;
    int nvidia_set = 0;
    int intel_set = 0;
    int x_options_matches = 0;
    char line[2048];
    char intel_bus_id[100];
    char nvidia_bus_id[100];
    FILE *file;


    if (!exists_not_empty(xorg_conf_file))
        return 0;

    file = fopen(xorg_conf_file, "r");

    if (!file) {
        fprintf(log_handle, "Error: I couldn't open %s for reading.\n",
                xorg_conf_file);
        return 0;
    }

    /* Get the BusIDs of each card. Let's be super paranoid about
     * the ordering on the bus, although there should be no surprises
     */
    for (i=0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL) {
            sprintf(intel_bus_id, "\"PCI:%d@%d:%d:%d\"",
                                  (int)(devices[i]->bus),
                                  (int)(devices[i]->domain),
                                  (int)(devices[i]->dev),
                                  (int)(devices[i]->func));
        }
        else if (devices[i]->vendor_id == NVIDIA) {
            sprintf(nvidia_bus_id, "\"PCI:%d@%d:%d:%d\"",
                                (int)(devices[i]->bus),
                                (int)(devices[i]->domain),
                                (int)(devices[i]->dev),
                                (int)(devices[i]->func));
        }
    }

    while (fgets(line, sizeof(line), file)) {
        /* Ignore comments */
        if (strstr(line, "#") == NULL) {
            /* Parse options here */
            if (istrstr(line, "Option") != NULL) {
                if ((istrstr(line, "AllowEmptyInitialConfiguration") != NULL &&
                    istrstr(line, "on") != NULL) ||
                    (istrstr(line, "ConstrainCursor") != NULL &&
                    istrstr(line, "off") != NULL)) {
                    x_options_matches += 1;
                }
            }
            else if (strstr(line, intel_bus_id) != NULL) {
                intel_matches += 1;
            }
            else if (cards_n >1 && strstr(line, nvidia_bus_id) != NULL) {
                nvidia_matches += 1;
            }
            /* The driver has to be either intel or nvidia */
            else if (istrstr(line, "Driver") != NULL) {
                if (istrstr(line, "modesetting") != NULL){
                    intel_set += 1;
                }
                else if (istrstr(line, "nvidia") != NULL) {
                    nvidia_set += 1;
                }
            }

        }
    }

    fclose(file);

    fprintf(log_handle,
            "intel_matches: %d, nvidia_matches: %d, "
            "intel_set: %d, nvidia_set: %d "
            "x_options_matches: %d\n",
            intel_matches, nvidia_matches,
            intel_set, nvidia_set,
            x_options_matches);

    if (cards_n == 1) {
        /* The module was probably unloaded when
         * the card was powered down
         */
        return (intel_matches == 1 &&
                intel_set == 1 && nvidia_set == 1 &&
                x_options_matches > 1);
    }
    else {
        return (intel_matches == 1 && nvidia_matches == 1 &&
                intel_set == 1 && nvidia_set == 1 &&
                x_options_matches > 1);
    }
}


/* Check xorg.conf to see if it's all properly set */
static int check_pxpress_xorg_conf(struct device **devices,
                                   int cards_n) {
    int i;
    int intel_matches = 0;
    int amd_matches = 0;
    int fglrx_set = 0;
    int intel_set = 0;
    int x_options_matches = 0;
    char line[2048];
    char intel_bus_id[100];
    char amd_bus_id[100];
    FILE *file;


    if (!exists_not_empty(xorg_conf_file))
        return 0;

    file = fopen(xorg_conf_file, "r");

    if (!file) {
        fprintf(log_handle, "Error: I couldn't open %s for reading.\n",
                xorg_conf_file);
        return 0;
    }

    /* Get the BusIDs of each card. Let's be super paranoid about
     * the ordering on the bus, although there should be no surprises
     */
    for (i=0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL) {
            sprintf(intel_bus_id, "\"PCI:%d@%d:%d:%d\"",
                                  (int)(devices[i]->bus),
                                  (int)(devices[i]->domain),
                                  (int)(devices[i]->dev),
                                  (int)(devices[i]->func));
        }
        else if (devices[i]->vendor_id == AMD) {
            /* FIXME: fglrx doesn't seem to support
             *        the domain, so we only use
             *        bus, dev, and func
             */
            /* sprintf(amd_bus_id, "\"PCI:%d@%d:%d:%d\"", */
            sprintf(amd_bus_id, "\"PCI:%d:%d:%d\"",
                                (int)(devices[i]->bus),
                                /*(int)(devices[i]->domain),*/
                                (int)(devices[i]->dev),
                                (int)(devices[i]->func));
        }
    }

    while (fgets(line, sizeof(line), file)) {
        /* Ignore comments */
        if (strstr(line, "#") == NULL) {
            /* Parse options here */
            if (istrstr(line, "Option") != NULL) {
                if (istrstr(line, "AccelMethod") != NULL &&
                    istrstr(line, "UXA") != NULL) {
                    x_options_matches += 1;
                }
            }
            else if (strstr(line, intel_bus_id) != NULL) {
                intel_matches += 1;
            }
            else if (cards_n >1 && strstr(line, amd_bus_id) != NULL) {
                amd_matches += 1;
            }
            /* The driver has to be either intel or fglrx */
            else if (istrstr(line, "Driver") != NULL) {
                if (istrstr(line, "intel") != NULL){
                    intel_set += 1;
                }
                else if (istrstr(line, "fglrx") != NULL) {
                    fglrx_set += 1;
                }
            }

        }
    }

    fclose(file);

    fprintf(log_handle,
            "intel_matches: %d, amd_matches: %d, "
            "intel_set: %d, fglrx_set: %d "
            "x_options_matches: %d\n",
            intel_matches, amd_matches,
            intel_set, fglrx_set,
            x_options_matches);

    if (cards_n == 1) {
        /* The module was probably unloaded when
         * the card was powered down
         */
        return (intel_matches == 1 &&
                intel_set == 1 && fglrx_set == 1 &&
                x_options_matches > 0);
    }
    else {
        return (intel_matches == 1 && amd_matches == 1 &&
                intel_set == 1 && fglrx_set == 1 &&
                x_options_matches > 0);
    }
}


static int check_vendor_bus_id_xorg_conf(struct device **devices, int cards_n,
                                         unsigned int vendor_id, char *driver) {
    int failure = 0;
    int i;
    int matches = 0;
    int expected_matches = 0;
    char line[4096];
    char bus_id[256];
    FILE *file;

    /* If file doesn't exist or is empty */
    if (!exists_not_empty(xorg_conf_file))
        return 0;

    file = fopen(xorg_conf_file, "r");

    if (!file) {
        fprintf(log_handle, "Error: I couldn't open %s for reading.\n",
                xorg_conf_file);
        return 0;
    }

    for (i=0; i < cards_n; i++) {
    /* BusID \"PCI:%d@%d:%d:%d\" */
        if (devices[i]->vendor_id == vendor_id)
            expected_matches += 1;
    }

    while (fgets(line, sizeof(line), file)) {
        /* Ignore comments */
        if (strstr(line, "#") == NULL) {
            /* If we find a line with the BusId */
            if (istrstr(line, "BusID") != NULL) {
                for (i=0; i < cards_n; i++) {
                    /* BusID \"PCI:%d@%d:%d:%d\" */
                    if (devices[i]->vendor_id == vendor_id) {
                        sprintf(bus_id, "\"PCI:%d@%d:%d:%d\"", (int)(devices[i]->bus),
                                                               (int)(devices[i]->domain),
                                                               (int)(devices[i]->dev),
                                                               (int)(devices[i]->func));
                        if (strstr(line, bus_id) != NULL) {
                            matches += 1;
                        }
                    }
                }
            }
            else if ((istrstr(line, "Driver") != NULL) &&
                     (strstr(line, driver) == NULL)) {
                failure = 1;
            }
        }
    }

    fclose(file);

    return (matches == expected_matches && !failure);
}


static int check_all_bus_ids_xorg_conf(struct device **devices, int cards_n) {
    /* int status = 0;*/
    int i;
    int matches = 0;
    char line[4096];
    char bus_id[256];
    FILE *file;

    file = fopen(xorg_conf_file, "r");

    if (!file) {
        fprintf(log_handle, "Error: I couldn't open %s for reading.\n",
                xorg_conf_file);
        return 0;
    }

    while (fgets(line, sizeof(line), file)) {
        for (i=0; i < cards_n; i++) {
            /* BusID \"PCI:%d@%d:%d:%d\" */
            sprintf(bus_id, "\"PCI:%d@%d:%d:%d\"", (int)(devices[i]->bus),
                                                   (int)(devices[i]->domain),
                                                   (int)(devices[i]->dev),
                                                   (int)(devices[i]->func));
            if (strstr(line, bus_id) != NULL) {
                matches += 1;
            }
        }
    }

    fclose(file);

    return (matches == cards_n);
    /* return status; */
}


static int write_prime_xorg_conf(struct device **devices, int cards_n) {
    int i;
    FILE *pfile = NULL;

    fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);

    pfile = fopen(xorg_conf_file, "w");
    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                xorg_conf_file);
        return 0;
    }

    fprintf(pfile,
            "Section \"ServerLayout\"\n"
            "    Identifier \"layout\"\n"
            "    Screen 0 \"nvidia\"\n"
            "    Inactive \"intel\"\n"
            "EndSection\n\n");

    for(i = 0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL) {
            fprintf(pfile,
                "Section \"Device\"\n"
                "    Identifier \"intel\"\n"
                "    Driver \"modesetting\"\n"
                "    BusID \"PCI:%d@%d:%d:%d\"\n"
                "EndSection\n\n"
                "Section \"Screen\"\n"
                "    Identifier \"intel\"\n"
                "    Device \"intel\"\n"
                "EndSection\n\n",
               (int)(devices[i]->bus),
               (int)(devices[i]->domain),
               (int)(devices[i]->dev),
               (int)(devices[i]->func));
        }
        else if (devices[i]->vendor_id == NVIDIA) {
            fprintf(pfile,
                "Section \"Device\"\n"
                "    Identifier \"nvidia\"\n"
                "    Driver \"nvidia\"\n"
                "    BusID \"PCI:%d@%d:%d:%d\"\n"
                "    Option \"ConstrainCursor\" \"off\"\n"
                "EndSection\n\n"
                "Section \"Screen\"\n"
                "    Identifier \"nvidia\"\n"
                "    Device \"nvidia\"\n"
                "    Option \"AllowEmptyInitialConfiguration\" \"on\"\n"
                "EndSection\n\n",
               (int)(devices[i]->bus),
               (int)(devices[i]->domain),
               (int)(devices[i]->dev),
               (int)(devices[i]->func));
        }
    }

    fflush(pfile);
    fclose(pfile);
    return 1;
}



/* Open a file and check if it contains "on"
 * or "off".
 *
 * Return 0 if the file doesn't exist or is empty.
 */
static int check_on_off(const char *path) {
    int status = 0;
    char line[100];
    FILE *file;

    file = fopen(path, "r");

    if (!file) {
        fprintf(log_handle, "Error: can't open %s\n", path);
        return 0;
    }

    while (fgets(line, sizeof(line), file)) {
        if (istrstr(line, "on") != NULL) {
            status = 1;
            break;
        }
    }

    fclose(file);

    return status;
}


/* Get the current status for PRIME from bbswitch.
 *
 * This tells us whether the discrete card is
 * on or off.
 */
static int prime_is_discrete_nvidia_on() {
    return (check_on_off(bbswitch_path));
}


/* Get the settings for PRIME.
 *
 * This tells us whether the discrete card should be
 * on or off.
 */
static int prime_is_action_on() {
    return (check_on_off(prime_settings));
}


static int prime_set_discrete(int mode) {
    FILE *file;

    file = fopen(bbswitch_path, "w");
    if (!file)
        return 0;

    fprintf(file, "%s\n", mode ? "ON" : "OFF");
    fclose(file);

    return 1;
}


/* Power on the NVIDIA discrete card */
static int prime_enable_discrete() {
    int status = 0;

    /* Set bbswitch */
    status = prime_set_discrete(1);

    /* Load the module */
    if (status)
        status = load_module("nvidia");

    return status;
}


/* Power off the NVIDIA discrete card */
static int prime_disable_discrete() {
    int status = 0;

    /* Tell nvidia-persistenced the nvidia card is about
     * to be switched off
     */
    if (!dry_run)
        system("/sbin/initctl emit nvidia-off");

    /* Unload the module */
    status = unload_module("nvidia");

    /* Set bbswitch */
    if (status)
        status = prime_set_discrete(0);

    return status;
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
                               unsigned int *vendor_id,
                               unsigned int *device_id) {
    int i;
    for(i = 0; i < cards_number; i++) {
        if (!devices[i]->boot_vga) {
            *vendor_id = devices[i]->vendor_id;
            *device_id = devices[i]->device_id;
            break;
        }
    }
}


static int has_system_changed(struct device **old_devices,
                       struct device **new_devices,
                       int old_number,
                       int new_number) {

    int status = 0;
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
            status = 1;
            break;
        }
    }

    return status;
}


static int write_data_to_file(struct device **devices,
                              int cards_number,
                              char *filename) {
    int i;
    FILE *pfile = NULL;
    pfile = fopen(filename, "w");
    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                filename);
        return 0;
    }

    for(i = 0; i < cards_number; i++) {
        fprintf(pfile, "%04x:%04x;%04x:%02x:%02x:%d;%d\n",
                devices[i]->vendor_id,
                devices[i]->device_id,
                devices[i]->domain,
                devices[i]->bus,
                devices[i]->dev,
                devices[i]->func,
                devices[i]->boot_vga);
    }
    fflush(pfile);
    fclose(pfile);
    return 1;
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


static int read_data_from_file(struct device **devices,
                               int *cards_number,
                               char *filename) {
    /* Read from last boot gfx */
    char line[100];
    FILE *pfile = NULL;
    /* The number of digits we expect to match per line */
    int desired_matches = 7;

    pfile = fopen(filename, "r");
    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for reading.\n", filename);
        /* Create the file for the 1st time */
        pfile = fopen(filename, "w");
        fprintf(log_handle, "Create %s for the 1st time\n", filename);
        if (pfile == NULL) {
            fprintf(log_handle, "I couldn't open %s for writing.\n",
                    filename);
            return 0;
        }
        fprintf(pfile, "%04x:%04x;%04x:%02x:%02x:%d;%d\n",
                0, 0, 0, 0, 0, 0, 0);
        fflush(pfile);
        fclose(pfile);
        /* Try again */
        pfile = fopen(filename, "r");
    }

    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for reading.\n", filename);
        return 0;
    }
    else {
        /* Use fgets so as to limit the buffer length */
        while (fgets(line, sizeof(line), pfile) && (*cards_number < MAX_CARDS_N)) {
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

    fclose(pfile);
    return 1;
}


/* Find pci id in dmesg stream */
static char * find_pci_pattern(char *line, const char *pattern) {
    int is_next = 0;
    char *tok;
    char *match = NULL;

    tok = strtok(line, " ");

    while (tok != NULL)
    {
        tok = strtok (NULL, " ");
        if (is_next) {
            if (tok && isdigit(tok[0])) {
                fprintf(log_handle, "Found %s pci id in dmesg: %s.\n",
                        pattern, tok);
                match = strdup(tok);
                break;
            }
            else {
                break;
            }
        }
        if (tok)
            is_next = (strcmp(tok, pattern) == 0);
    }

    return match;
}


/* Parse part of dmesg to extract the PCI BusID */
static int add_gpu_from_stream(FILE *pfile, const char *pattern, struct device **devices, int *num) {
    int status = EOF;
    char line[1035];
    char *match = NULL;
    /* The number of digits we expect to match per line */
    int desired_matches = 4;

    if (!pfile) {
        fprintf(log_handle, "Error: passed invalid stream.\n");
        return 0;
    }

    devices[*num] = malloc(sizeof(struct device));

    if (!devices[*num])
        return 0;

    while (fgets(line, sizeof(line), pfile)) {
        match = find_pci_pattern(line, pattern);
        if (match) {
            /* Extract the data from the string */
            status = sscanf(match, "%04x:%02x:%02x.%d\n",
                            &devices[*num]->domain,
                            &devices[*num]->bus,
                            &devices[*num]->dev,
                            &devices[*num]->func);
            free(match);
            break;
        }
    }

    /* Check that we actually matched all the desired digits,
     * as per "desired_matches"
     */
    if (status == EOF || status != desired_matches) {
        free(devices[*num]);
        return 0;
    }

    if (istrstr(pattern, "nvidia") != NULL) {
        /* Add fake device and vendor ids */
        devices[*num]->vendor_id = NVIDIA;
        devices[*num]->device_id = 0x68d8;
    }
    else if (istrstr(pattern, "fglrx") != NULL){
        /* Add fake device and vendor ids */
        devices[*num]->vendor_id = AMD;
        devices[*num]->device_id = 0x68d8;
    }

    /* Increment number of cards */
    *num += 1;

    return status;
}


/* Get the PCI BusID from dmesg */
static int add_gpu_bus_from_dmesg(const char *pattern, struct device **devices,
                                  int *cards_number) {
    int status = 0;
    char command[100];
    FILE *pfile = NULL;

    if (dry_run && fake_dmesg_path) {
        /* If file doesn't exist or is empty */
        if (!exists_not_empty(fake_dmesg_path))
            return 0;

        sprintf(command, "grep %s %s",
                pattern, fake_dmesg_path);
    }
    else {
        sprintf(command, "dmesg | grep %s", pattern);
    }

    pfile = popen(command, "r");
    if (pfile == NULL) {
        return 1;
    }

    /* Extract ID from the stream */
    status = add_gpu_from_stream(pfile, pattern, devices, cards_number);

    pclose(pfile);

    fprintf(log_handle, "pci bus from dmesg status %d\n", status);

    return status;
}


/* Get the PCI BusID from dmesg */
static int add_amd_gpu_bus_from_dmesg(struct device **devices,
                                  int *cards_number) {

    return (add_gpu_bus_from_dmesg("fglrx_pci", devices, cards_number));
}

static int add_nvidia_gpu_bus_from_dmesg(struct device **devices,
                                  int *cards_number) {
    return (add_gpu_bus_from_dmesg("nvidia", devices, cards_number));
}

static int is_module_loaded(const char *module) {
    int status = 0;
    char line[4096];
    FILE *file;
    if (!fake_modules_path)
        file = fopen("/proc/modules", "r");
    else
        file = fopen(fake_modules_path, "r");

    if (!file) {
        fprintf(log_handle, "Error: can't open /proc/modules");
        return 0;
    }

    while (fgets(line, sizeof(line), file)) {
        char *tok;
        tok = strtok(line, " \t");
        if (strstr(tok, module) != NULL) {
            status = 1;
            break;
        }
    }

    fclose(file);

    return status;
}

static int is_file(char *file) {
    struct stat stbuf;

    if (stat(file, &stbuf) == -1) {
        fprintf(log_handle, "Error: can't access %s\n", file);
        return 0;
    }
    if (stbuf.st_mode & S_IFMT)
        return 1;

    return 0;
}

static int is_dir(char *directory) {
    struct stat stbuf;

    if (stat(directory, &stbuf) == -1) {
        fprintf(log_handle, "Error: can't access %s\n", directory);
        return 0;
    }
    if ((stbuf.st_mode & S_IFMT) == S_IFDIR)
        return 1;
    return 0;
}

static int is_dir_empty(char *directory) {
    int n = 0;
    struct dirent *d;
    DIR *dir = opendir(directory);
    if (dir == NULL)
        return 1;
    while ((d = readdir(dir)) != NULL) {
        if(++n > 2)
        break;
    }
    closedir(dir);
    if (n <= 2)
        return 1;
    else
        return 0;
}

static int is_link(char *file) {
    struct stat stbuf;

    if (lstat(file, &stbuf) == -1) {
        fprintf(log_handle, "Error: can't access %s\n", file);
        return 0;
    }
    if ((stbuf.st_mode & S_IFMT) == S_IFLNK)
        return 1;

    return 0;
}


/* See if the device is bound to a driver */
static int is_device_bound_to_driver(struct pci_device *info) {
    char sysfs_path[256];
    sprintf(sysfs_path, "/sys/bus/pci/devices/%04x:%02x:%02x.%d/driver",
            info->domain, info->bus, info->dev, info->func);

    return(is_link(sysfs_path));
}


/* Count the number of outputs connected to the card */
int count_connected_outputs(int fd, drmModeResPtr res) {
    int i;
    int connected_outputs = 0;
    drmModeConnectorPtr connector;

    for (i = 0; i < res->count_connectors; i++) {
        connector = drmModeGetConnector(fd, res->connectors[i]);

        if (connector) {
            switch (connector->connection) {
            case DRM_MODE_CONNECTED:
                fprintf(log_handle, "output %d:\n", connected_outputs);
                connected_outputs += 1;

                switch (connector->connector_type) {
                case DRM_MODE_CONNECTOR_Unknown:
                    fprintf(log_handle, "\tunknown connector\n");
                    break;
                case DRM_MODE_CONNECTOR_VGA:
                    fprintf(log_handle, "\tVGA connector\n");
                    break;
                case DRM_MODE_CONNECTOR_DVII:
                    fprintf(log_handle, "\tDVII connector\n");
                    break;
                case DRM_MODE_CONNECTOR_DVID:
                    fprintf(log_handle, "\tDVID connector\n");
                    break;
                case DRM_MODE_CONNECTOR_DVIA:
                    fprintf(log_handle, "\tDVIA connector\n");
                    break;
                case DRM_MODE_CONNECTOR_Composite:
                    fprintf(log_handle, "\tComposite connector\n");
                    break;
                case DRM_MODE_CONNECTOR_SVIDEO:
                    fprintf(log_handle, "\tSVIDEO connector\n");
                    break;
                case DRM_MODE_CONNECTOR_LVDS:
                    fprintf(log_handle, "\tLVDS connector\n");
                    break;
                case DRM_MODE_CONNECTOR_Component:
                    fprintf(log_handle, "\tComponent connector\n");
                    break;
                case DRM_MODE_CONNECTOR_9PinDIN:
                    fprintf(log_handle, "\t9PinDIN connector\n");
                    break;
                case DRM_MODE_CONNECTOR_DisplayPort:
                    fprintf(log_handle, "\tDisplayPort connector\n");
                    break;
                case DRM_MODE_CONNECTOR_HDMIA:
                    fprintf(log_handle, "\tHDMIA connector\n");
                    break;
                case DRM_MODE_CONNECTOR_HDMIB:
                    fprintf(log_handle, "\tHDMIB connector\n");
                    break;
                case DRM_MODE_CONNECTOR_TV:
                    fprintf(log_handle, "\tTV connector\n");
                    break;
                case DRM_MODE_CONNECTOR_eDP:
                    fprintf(log_handle, "\teDP connector\n");
                    break;
#if 0
                case DRM_MODE_CONNECTOR_VIRTUAL:
                    fprintf(log_handle, "VIRTUAL connector\n");
                    break;
                case DRM_MODE_CONNECTOR_DSI:
                    fprintf(log_handle, "DSI connector\n");
                    break;
#endif
                default:
                    break;
                }


                break;
            case DRM_MODE_DISCONNECTED:
                break;
            default:
                break;
            }
            drmModeFreeConnector(connector);
        }
    }
    return connected_outputs;
}


/* See if the drm device created by a driver has any connected outputs. */
static int has_driver_connected_outputs(const char *driver) {
    char path[20];
    int fd = 1;
    drmModeResPtr res;
    drmVersionPtr version;
    int connected_outputs = 0;
    int driver_match = 0;
    int it;

    /* Keep looking until we find the device for the driver */
    for (it = 0; fd != -1; it++) {
        sprintf(path, "/dev/dri/card%d", it);
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
            break;
        }
    }

    if (!driver_match)
        return 0;

    res = drmModeGetResources(fd);
    if (!res) {
        fprintf(log_handle, "Error: can't get drm resources.\n");
        drmClose(fd);
        return 0;
    }


    connected_outputs = count_connected_outputs(fd, res);

    fprintf(log_handle, "Number of connected outputs for %s: %d\n", path, connected_outputs);

    drmModeFreeResources(res);

    close(fd);

    return (connected_outputs > 0);
}


/* Check if any outputs are still connected to card0.
 *
 * By default we only check cards driver by i915.
 * If so, then claim support for RandR offloading
 */
static int requires_offloading(void) {

    /* Let's check only /dev/dri/card0 and look
     * for driver i915. We don't want to enable
     * offloading to any other driver, as results
     * may be unpredictable
     */
    return(has_driver_connected_outputs("i915"));
}


/* Set permanent settings for offloading */
static int set_offloading(void) {
    FILE *file;

    if (dry_run)
        return 1;

    file = fopen(OFFLOADING_CONF, "w");
    if (file != NULL) {
        fprintf(file, "ON\n");
        fflush(file);
        fclose(file);
        return 1;
    }

    return 0;
}


/* Make a backup and remove xorg.conf */
static int remove_xorg_conf(void) {
    int status;
    char backup[200];
    char buffer[80];
    time_t rawtime;
    struct tm *info;

    fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);

    time(&rawtime);
    info = localtime(&rawtime);

    strftime(buffer, 80, "%m%d%Y", info);
    sprintf(backup, "%s.%s", xorg_conf_file, buffer);

    status = rename(xorg_conf_file, backup);
    if (!status) {
        status = unlink(xorg_conf_file);
        if (!status)
            return 0;
        else
            return 1;
    }
    else {
        fprintf(log_handle, "Moved %s to %s\n", xorg_conf_file, backup);
    }
    return 1;
}


static int enable_mesa() {
    int status = 0;
    fprintf(log_handle, "Selecting mesa\n");
    status = select_driver("mesa");

    /* Remove xorg.conf */
    remove_xorg_conf();

    return status;
}


static int enable_nvidia(struct alternatives *alternative,
                         unsigned int vendor_id,
                         struct device **devices,
                         int cards_n) {
    int status = 0;

    /* Alternative not in use */
    if (!alternative->nvidia_enabled) {
        /* Select nvidia */
        fprintf(log_handle, "Selecting nvidia\n");
        status = select_driver("nvidia");
        /* select_driver(other_arch_path, "nvidia"); */
    }
    /* Alternative in use */
    else {
        fprintf(log_handle, "Driver is already loaded and enabled\n");
        status = 1;
    }
    /* See if enabling the driver failed */
    if (status) {
        /* If xorg.conf exists, make sure it contains
         * the right BusId and NO NOUVEAU or FGLRX. If it doesn't, create a
         * xorg.conf from scratch */
        if (!check_vendor_bus_id_xorg_conf(devices, cards_n,
                                           vendor_id, "nvidia")) {
            fprintf(log_handle, "Check failed\n");

            /* Remove xorg.conf */
            remove_xorg_conf();

            /* Only useful if more than one card is available */
            if (cards_n > 1) {
                /* Write xorg.conf */
                write_to_xorg_conf(devices, cards_n, vendor_id);
            }
        }
        else {
            fprintf(log_handle, "No need to modify xorg.conf. Path: %s\n", xorg_conf_file);
        }
    }
    else {
        /* For some reason we failed to select the
         * driver. Let's select Mesa here */
        fprintf(log_handle, "Error: failed to enable the driver\n");
        enable_mesa();
    }

    return status;
}


static int enable_prime(const char *prime_settings,
                        int bbswitch_loaded,
                        unsigned int vendor_id,
                        struct alternatives *alternative,
                        struct device **devices,
                        int cards_n) {
    int status = 0;
    int prime_discrete_on = 0;
    int prime_action_on = 0;

    /* We only support Lightdm at this time */
    if (!is_lightdm_default()) {
        fprintf(log_handle, "Lightdm is not the default display "
                            "manager. Nothing to do\n");
        return 0;
    }

    /* Check if prime_settings is available
     * File doesn't exist or empty
     */
    if (!exists_not_empty(prime_settings)) {
        fprintf(log_handle, "Error: no settings for prime can be found in %s\n",
                prime_settings);
        return 0;
    }

    if (!bbswitch_loaded) {
        /* Try to load bbswitch */
        /* opts="`/sbin/get-quirk-options`"
        /sbin/modprobe bbswitch load_state=-1 unload_state=1 "$opts" || true */
        status = load_bbswitch();
        if (!status) {
            fprintf(log_handle, "Error: can't load bbswitch\n");
            /* Select mesa as a fallback */
            enable_mesa();

            /* Remove xorg.conf */
            remove_xorg_conf();
            return 0;
        }
    }

    /* Get the current status from bbswitch */
    prime_discrete_on = prime_is_discrete_nvidia_on();
    /* Get the current settings for discrete */
    prime_action_on = prime_is_action_on();

    if (prime_action_on) {
        if (!alternative->nvidia_enabled) {
            /* Select nvidia */
            enable_nvidia(alternative, vendor_id, devices, cards_n);
        }

        if (!check_prime_xorg_conf(devices, cards_n)) {
            fprintf(log_handle, "Check failed\n");

            /* Remove xorg.conf */
            remove_xorg_conf();
            /* Write xorg.conf */
            write_prime_xorg_conf(devices, cards_n);
        }
        else {
            fprintf(log_handle, "No need to modify xorg.conf. Path: %s\n", xorg_conf_file);
        }
    }
    else {
        if (!alternative->prime_enabled) {
            /* Select prime */
            fprintf(log_handle, "Selecting prime\n");
            select_driver("prime");
        }

        /* Remove xorg.conf */
        remove_xorg_conf();
    }

    /* This means we need to call bbswitch
     * to take action
     */
    if (prime_action_on == prime_discrete_on) {
        fprintf(log_handle, "No need to change the current bbswitch status\n");
        return 1;
    }

    if (prime_action_on) {
        fprintf(log_handle, "Powering on the discrete card\n");
        prime_enable_discrete();
    }
    else {
        fprintf(log_handle, "Powering off the discrete card\n");
        prime_disable_discrete();
    }

    return 1;
}


static int enable_fglrx(struct alternatives *alternative,
                        unsigned int vendor_id,
                        struct device **devices,
                        int cards_n) {
    int status = 0;

    /* Alternative not in use */
    if (!alternative->fglrx_enabled) {
        /* Select fglrx */
        fprintf(log_handle, "Selecting fglrx\n");
        status = select_driver("fglrx");
        /* select_driver(other_arch_path, "nvidia"); */
    }
    /* Alternative in use */
    else {
        fprintf(log_handle, "Driver is already loaded and enabled\n");
        status = 1;
    }

    if (status) {
        /* If xorg.conf exists, make sure it contains
         * the right BusId and NO NOUVEAU or FGLRX. If it doesn't, create a
         * xorg.conf from scratch */
        if (!check_vendor_bus_id_xorg_conf(devices, cards_n,
                                           vendor_id, "fglrx")) {
            fprintf(log_handle, "Check failed\n");

            /* Remove xorg.conf */
            remove_xorg_conf();

            /* Only useful if more than one card is available */
            if (cards_n > 1) {
                /* Write xorg.conf */
                write_to_xorg_conf(devices, cards_n, vendor_id);
            }
        }
        else {
            fprintf(log_handle, "No need to modify xorg.conf. Path: %s\n", xorg_conf_file);
        }
    }
    else {
        /* For some reason we failed to select the
         * driver. Let's select Mesa here */
        fprintf(log_handle, "Error: failed to enable the driver\n");
        enable_mesa();
    }

    return status;
}


static int enable_pxpress(struct device **devices,
                          int cards_n) {
    int status = 0;

    /* FIXME: check only xorg.conf for now */
    if (!check_pxpress_xorg_conf(devices, cards_n)) {
        fprintf(log_handle, "Check failed\n");

        /* Remove xorg.conf */
        remove_xorg_conf();
        /* Write xorg.conf */
        status = write_pxpress_xorg_conf(devices, cards_n);
    }
    else {
        fprintf(log_handle, "No need to modify xorg.conf. Path: %s\n", xorg_conf_file);
        status = 1;
    }

    /* Reenable this when we know more about amdpcsdb */
#if 0
    /* See if the discrete GPU is disabled */
    if (is_pxpress_dgpu_disabled()) {
        if (!alternative->pxpress_enabled) {
            fprintf(log_handle, "Selecting pxpress\n");
            status = select_driver("pxpress");
        }
        else {
            fprintf(log_handle, "Driver is already loaded and enabled\n");
            status = 1;
        }
    }
    else {
        if (!alternative->fglrx_enabled) {
            fprintf(log_handle, "Selecting fglrx\n");
            status = select_driver("fglrx");
        }
        else {
            fprintf(log_handle, "Driver is already loaded and enabled\n");
            status = 1;
        }
    }

    if (status) {
        /* If xorg.conf exists, make sure it contains
         * the right BusId and the correct drivers. If it doesn't, create a
         * xorg.conf from scratch */
        if (!check_pxpress_xorg_conf(current_devices, cards_n)) {
            fprintf(log_handle, "Check failed\n");

            /* Remove xorg.conf */
            remove_xorg_conf();
            /* Write xorg.conf */
            write_pxpress_xorg_conf(current_devices, cards_n);
        }
        else {
            fprintf(log_handle, "No need to modify xorg.conf. Path: %s\n", xorg_conf_file);
        }
    }
    else {
        /* For some reason we failed to select the
         * driver. Let's select Mesa here */
        fprintf(log_handle, "Error: failed to enable the driver\n");
        fprintf(log_handle, "Selecting mesa\n");
        select_driver("mesa");
        /* select_driver(other_arch_path, "mesa"); */
        /* Remove xorg.conf */
        remove_xorg_conf();
    }
#endif

    return status;
}




int main(int argc, char *argv[]) {

    int opt, i;
    char *fake_lspci_file = NULL;
    char *new_boot_file = NULL;

    static int fake_offloading = 0;

    int has_intel = 0, has_amd = 0, has_nvidia = 0;
    int has_changed = 0;
    int has_moved_xorg_conf = 0;
    int nvidia_loaded = 0, fglrx_loaded = 0,
        intel_loaded = 0, radeon_loaded = 0,
        nouveau_loaded = 0, bbswitch_loaded = 0;
    int fglrx_unloaded = 0, nvidia_unloaded = 0;
    int offloading = 0;
    int status = 0;

    /* Vendor and device id (boot vga) */
    unsigned int boot_vga_vendor_id = 0, boot_vga_device_id = 0;

    /* Vendor and device id (discrete) */
    unsigned int discrete_vendor_id = 0, discrete_device_id = 0;

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

    /* Alternatives */
    struct alternatives *alternative = NULL;


    while (1) {
        static struct option long_options[] =
        {
        /* These options set a flag. */
        {"dry-run", no_argument,     &dry_run, 1},
        {"fake-requires-offloading", no_argument, &fake_offloading, 1},
        {"fake-no-requires-offloading", no_argument, &fake_offloading, 0},
        {"fake-lightdm", no_argument, &fake_lightdm, 1},
        /* These options don't set a flag.
          We distinguish them by their indices. */
        {"log",  required_argument, 0, 'l'},
        {"fake-lspci",  required_argument, 0, 'f'},
        {"last-boot-file", required_argument, 0, 'b'},
        {"new-boot-file", required_argument, 0, 'n'},
        {"xorg-conf-file", required_argument, 0, 'x'},
        {"amd-pcsdb-file", required_argument, 0, 'd'},
        {"fake-alternative", required_argument, 0, 'a'},
        {"fake-modules-path", required_argument, 0, 'm'},
        {"fake-alternatives-path", required_argument, 0, 'p'},
        {"fake-dmesg-path", required_argument, 0, 's'},
        {"prime-settings", required_argument, 0, 'z'},
        {"bbswitch-path", required_argument, 0, 'y'},
        {"bbswitch-quirks-path", required_argument, 0, 'g'},
        {"dmi-product-version-path", required_argument, 0, 'h'},
        {0, 0, 0, 0}
        };
        /* getopt_long stores the option index here. */
        int option_index = 0;

        opt = getopt_long (argc, argv, "lbnfxdampzy:::",
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
            case 'x':
                /* printf("option -x with value '%s'\n", optarg); */
                xorg_conf_file = malloc(strlen(optarg) + 1);
                if (xorg_conf_file)
                    strcpy(xorg_conf_file, optarg);
                else
                    abort();
                break;
            case 'd':
                /* printf("option -x with value '%s'\n", optarg); */
                amd_pcsdb_file = malloc(strlen(optarg) + 1);
                if (amd_pcsdb_file)
                    strcpy(amd_pcsdb_file, optarg);
                else
                    abort();
                break;
            case 'a':
                /* printf("option -a with value '%s'\n", optarg); */
                alternative = calloc(1, sizeof(struct alternatives));
                if (!alternative) {
                    abort();
                }
                else {
                    alternative->current = strdup(optarg);
                    if (!alternative->current) {
                        free(alternative);
                        abort();
                    }
                }
                break;
            case 'm':
                /* printf("option -m with value '%s'\n", optarg); */
                fake_modules_path = malloc(strlen(optarg) + 1);
                if (fake_modules_path)
                    strcpy(fake_modules_path, optarg);
                else
                    abort();
                break;
            case 'p':
                /* printf("option -p with value '%s'\n", optarg); */
                fake_alternatives_path = malloc(strlen(optarg) + 1);
                if (fake_alternatives_path)
                    strcpy(fake_alternatives_path, optarg);
                else
                    abort();
                break;
            case 's':
                /* printf("option -p with value '%s'\n", optarg); */
                fake_dmesg_path = malloc(strlen(optarg) + 1);
                if (fake_dmesg_path)
                    strcpy(fake_dmesg_path, optarg);
                else
                    abort();
                break;
            case 'z':
                /* printf("option -p with value '%s'\n", optarg); */
                prime_settings = strdup(optarg);
                if (!prime_settings)
                    abort();
                break;
            case 'y':
                /* printf("option -p with value '%s'\n", optarg); */
                bbswitch_path = strdup(optarg);
                if (!bbswitch_path)
                    abort();
                break;
            case 'g':
                /* printf("option -p with value '%s'\n", optarg); */
                bbswitch_quirks_path = strdup(optarg);
                if (!bbswitch_quirks_path)
                    abort();
                break;
            case 'h':
                /* printf("option -p with value '%s'\n", optarg); */
                dmi_product_version_path = strdup(optarg);
                if (!dmi_product_version_path)
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
        log_handle = fopen(log_file, "w");
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

    if (xorg_conf_file)
        fprintf(log_handle, "xorg.conf file: %s\n", xorg_conf_file);
    else {
        xorg_conf_file = strdup(XORG_CONF);
        if (!xorg_conf_file) {
            fprintf(log_handle, "Couldn't allocate xorg_conf_file\n");
            goto end;
        }
    }

    if (prime_settings)
        fprintf(log_handle, "prime_settings file: %s\n", prime_settings);
    else {
        prime_settings = strdup("/etc/prime-discrete");
        if (!prime_settings) {
            fprintf(log_handle, "Couldn't allocate prime_settings\n");
            goto end;
        }
    }

    if (bbswitch_path)
        fprintf(log_handle, "bbswitch_path file: %s\n", bbswitch_path);
    else {
        bbswitch_path = strdup("/proc/acpi/bbswitch");
        if (!bbswitch_path) {
            fprintf(log_handle, "Couldn't allocate bbswitch_path\n");
            goto end;
        }
    }

    if (bbswitch_quirks_path)
        fprintf(log_handle, "bbswitch_quirks_path file: %s\n", bbswitch_quirks_path);
    else {
        bbswitch_quirks_path = strdup("/usr/share/nvidia-prime/prime-quirks");
        if (!bbswitch_quirks_path) {
            fprintf(log_handle, "Couldn't allocate bbswitch_quirks_path\n");
            goto end;
        }
    }

    if (dmi_product_version_path)
        fprintf(log_handle, "bbswitch_path file: %s\n", dmi_product_version_path);
    else {
        dmi_product_version_path = strdup("/sys/class/dmi/id/product_version");
        if (!dmi_product_version_path) {
            fprintf(log_handle, "Couldn't allocate dmi_product_version_path\n");
            goto end;
        }
    }

    if (amd_pcsdb_file)
        fprintf(log_handle, "amd_pcsdb_file file: %s\n", amd_pcsdb_file);
    else {
        amd_pcsdb_file = malloc(strlen("/etc/ati/amdpcsdb") + 1);
        if (amd_pcsdb_file) {
            strcpy(amd_pcsdb_file, "/etc/ati/amdpcsdb");
        }
        else {
            fprintf(log_handle, "Couldn't allocate amd_pcsdb_file\n");
            goto end;
        }
    }

    /* Either simulate or check if dealing with a system than requires RandR offloading */
    if (fake_lspci_file)
        offloading = fake_offloading;
    else
        offloading = requires_offloading();

    fprintf(log_handle, "Does it require offloading? %s\n", (offloading ? "yes" : "no"));

    /* Remove a file that will tell other apps such as
     * nvidia-prime if we need to offload rendering.
     */
    if (!offloading && !dry_run)
        unlink(OFFLOADING_CONF);

    bbswitch_loaded = is_module_loaded("bbswitch");
    nvidia_loaded = is_module_loaded("nvidia");
    nvidia_unloaded = has_unloaded_module("nvidia");
    fglrx_loaded = is_module_loaded("fglrx");
    fglrx_unloaded = has_unloaded_module("fglrx");
    intel_loaded = is_module_loaded("i915") || is_module_loaded("i810");
    radeon_loaded = is_module_loaded("radeon");
    nouveau_loaded = is_module_loaded("nouveau");

    fprintf(log_handle, "Is nvidia loaded? %s\n", (nvidia_loaded ? "yes" : "no"));
    fprintf(log_handle, "Was nvidia unloaded? %s\n", (nvidia_unloaded ? "yes" : "no"));
    fprintf(log_handle, "Is fglrx loaded? %s\n", (fglrx_loaded ? "yes" : "no"));
    fprintf(log_handle, "Was fglrx unloaded? %s\n", (fglrx_unloaded ? "yes" : "no"));
    fprintf(log_handle, "Is intel loaded? %s\n", (intel_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is radeon loaded? %s\n", (radeon_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is nouveau loaded? %s\n", (nouveau_loaded ? "yes" : "no"));

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
                has_nvidia = 1;
            }
            else if (current_devices[i]->vendor_id == AMD) {
                has_amd = 1;
            }
            else if (current_devices[i]->vendor_id == INTEL) {
                has_intel = 1;
            }
        }
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
                    fprintf(log_handle, "The device is not bound to any driver. Skipping...\n");
                    continue;
                }

                /* char *driver = NULL; */
                if (info->vendor_id == NVIDIA) {
                    has_nvidia = 1;
                }
                else if (info->vendor_id == INTEL) {
                    has_intel = 1;
                }
                else if (info->vendor_id == AMD) {
                    has_amd = 1;
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
    }

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


    /* Check alternatives */
    get_architecture_paths(&main_arch_path, &other_arch_path);

    if (!main_arch_path) {
        fprintf(stderr,
                "Error: the current architecture is not supported\n");
        goto end;
    }

    fprintf(log_handle, "main_arch_path %s, other_arch_path %s\n",
           main_arch_path, other_arch_path);

    /* If alternative is not NULL, then it's a test */
    if (!alternative)
        alternative = calloc(1, sizeof(struct alternatives));
    get_alternatives(alternative, main_arch_path);

    if (!alternative->current) {
        fprintf(stderr, "Error: no alternative found\n");
        goto end;
    }

    fprintf(log_handle, "Current alternative: %s\n", alternative->current);

    fprintf(log_handle, "Is nvidia enabled? %s\n", alternative->nvidia_enabled ? "yes" : "no");
    fprintf(log_handle, "Is fglrx enabled? %s\n", alternative->fglrx_enabled ? "yes" : "no");
    fprintf(log_handle, "Is mesa enabled? %s\n", alternative->mesa_enabled ? "yes" : "no");
    fprintf(log_handle, "Is pxpress enabled? %s\n", alternative->pxpress_enabled ? "yes" : "no");
    fprintf(log_handle, "Is prime enabled? %s\n", alternative->prime_enabled ? "yes" : "no");

    fprintf(log_handle, "Is nvidia available? %s\n", alternative->nvidia_available ? "yes" : "no");
    fprintf(log_handle, "Is fglrx available? %s\n", alternative->fglrx_available ? "yes" : "no");
    fprintf(log_handle, "Is mesa available? %s\n", alternative->mesa_available ? "yes" : "no");
    fprintf(log_handle, "Is pxpress available? %s\n", alternative->pxpress_available ? "yes" : "no");
    fprintf(log_handle, "Is prime available? %s\n", alternative->prime_available ? "yes" : "no");

    /* If the module is loaded but the alternatives are not there
     * we're probably dealing with a proprietary installer
     */
    if ((fglrx_loaded && !alternative->fglrx_available) ||
        (nvidia_loaded && !alternative->nvidia_available)) {
        fprintf(log_handle, "Proprietary driver installer detected\n");
        fprintf(log_handle, "Nothing to do\n");
        goto end;
    }

    if (has_changed)
        fprintf(log_handle, "System configuration has changed\n");

    if (cards_n == 1) {
        fprintf(log_handle, "Single card detected\n");

        /* Get data about the boot_vga card */
        get_boot_vga(current_devices, cards_n,
                     &boot_vga_vendor_id,
                     &boot_vga_device_id);

        if (boot_vga_vendor_id == INTEL) {
            /* AMD PowerXpress */
            if (offloading && fglrx_unloaded) {
                fprintf(log_handle, "PowerXpress detected\n");

                /* Get the BusID of the disabled discrete from dmesg */
                add_amd_gpu_bus_from_dmesg(current_devices, &cards_n);

                /* Get data about the first discrete card */
                get_first_discrete(current_devices, cards_n,
                                   &discrete_vendor_id,
                                   &discrete_device_id);

                enable_pxpress(current_devices, cards_n);
                /* No further action */
                goto end;
            }
            else if (offloading && nvidia_unloaded) {
                /* NVIDIA PRIME */
                fprintf(log_handle, "PRIME detected\n");

                /* Get the BusID of the disabled discrete from dmesg */
                add_nvidia_gpu_bus_from_dmesg(current_devices, &cards_n);

                /* Get data about the first discrete card */
                get_first_discrete(current_devices, cards_n,
                                   &discrete_vendor_id,
                                   &discrete_device_id);

                /* Try to enable prime */
                enable_prime(prime_settings, bbswitch_loaded,
                             discrete_vendor_id, alternative,
                             current_devices, cards_n);

                /* Write permanent settings about offloading */
                set_offloading();

                goto end;
            }
            else {
                if (!alternative->mesa_enabled) {
                    /* Select mesa */
                    status = enable_mesa();
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
        }
        else if (boot_vga_vendor_id == AMD) {
            /* if fglrx is loaded enable fglrx alternative */
            if (fglrx_loaded && !radeon_loaded) {
                if (!alternative->fglrx_enabled) {
                    /* Try to enable fglrx */
                    enable_fglrx(alternative, discrete_vendor_id, current_devices, cards_n);
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Driver is already loaded and enabled\n");
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
            else {
                /* If both the closed kernel module and the open
                 * kernel module are loaded, then we're in trouble
                 */
                if (fglrx_loaded && radeon_loaded) {
                    /* Fake a system change to trigger
                     * a reconfiguration
                     */
                    has_changed = 1;
                }

                /* Select mesa as a fallback */
                fprintf(log_handle, "Kernel Module is not loaded\n");
                if (!alternative->mesa_enabled) {
                    status = enable_mesa();
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
        }
        else if (boot_vga_vendor_id == NVIDIA) {
            /* if nvidia is loaded enable nvidia alternative */
            if (nvidia_loaded && !nouveau_loaded) {
                if (!alternative->nvidia_enabled) {
                    /* Try to enable nvidia */
                    enable_nvidia(alternative, discrete_vendor_id, current_devices, cards_n);
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Driver is already loaded and enabled\n");
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
            else {
                /* If both the closed kernel module and the open
                 * kernel module are loaded, then we're in trouble
                 */
                if (nvidia_loaded && nouveau_loaded) {
                    /* Fake a system change to trigger
                     * a reconfiguration
                     */
                    has_changed = 1;
                }

                /* Select mesa as a fallback */
                fprintf(log_handle, "Kernel Module is not loaded\n");
                if (!alternative->mesa_enabled) {
                    status = enable_mesa();
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
        }

        /* Move away xorg.conf */
        if (has_changed) {
            /* Either a desktop or a muxed laptop */
            fprintf(log_handle, "System configuration has changed\n");

            if (!has_moved_xorg_conf) {
                /* Remove xorg.conf */
                remove_xorg_conf();
            }
        }
        else if (!has_moved_xorg_conf) {
            fprintf(log_handle, "No change - nothing to do\n");
        }
    }
    else if (cards_n > 1) {
        /* Get data about the boot_vga card */
        get_boot_vga(current_devices, cards_n,
                     &boot_vga_vendor_id,
                     &boot_vga_device_id);

        /* Get data about the first discrete card */
        get_first_discrete(current_devices, cards_n,
                           &discrete_vendor_id,
                           &discrete_device_id);

        /* Intel + another GPU */
        if (boot_vga_vendor_id == INTEL) {
            fprintf(log_handle, "Intel IGP detected\n");
            /* AMD PowerXpress */
            if (offloading && intel_loaded && fglrx_loaded && !radeon_loaded) {
                fprintf(log_handle, "PowerXpress detected\n");

                enable_pxpress(current_devices, cards_n);
            }
            /* NVIDIA Optimus */
            else if (offloading && (intel_loaded && !nouveau_loaded &&
                                (alternative->nvidia_available ||
                                 alternative->prime_available) &&
                                 nvidia_loaded)) {
                fprintf(log_handle, "Intel hybrid system\n");

                enable_prime(prime_settings, bbswitch_loaded,
                             discrete_vendor_id, alternative,
                             current_devices, cards_n);

                /* Write permanent settings about offloading */
                set_offloading();

                goto end;
            }
            else {
                /* Desktop system or Laptop with open drivers only */
                fprintf(log_handle, "Desktop system detected\n");
                fprintf(log_handle, "or laptop with open drivers\n");

                /* TODO: Check the alternative and the module */
                /* If open source driver for the discrete card:
                 * i.e. proprietary modules are not loaded and
                 * open drivers are: if proprietary in xorg.conf,
                 * move the file away.
                 */

                if (discrete_vendor_id == NVIDIA) {
                    fprintf(log_handle, "Discrete NVIDIA card detected\n");

                    /* Kernel module is available */
                    if (nvidia_loaded && !nouveau_loaded) {
                        /* Try to enable nvidia */
                        enable_nvidia(alternative, discrete_vendor_id, current_devices, cards_n);
                    }
                    /* Kernel module is not available */
                    else {
                        /* If both the closed kernel module and the open
                         * kernel module are loaded, then we're in trouble
                         */
                        if (nvidia_loaded && nouveau_loaded) {
                            /* Fake a system change to trigger
                             * a reconfiguration
                             */
                            has_changed = 1;
                        }

                        /* See if alternatives are broken */
                        if (!alternative->mesa_enabled) {
                            /* Select mesa as a fallback */
                            fprintf(log_handle, "Kernel Module is not loaded\n");
                            status = enable_mesa();
                        }
                        else {
                            /* If the system has changed or a binary driver is still
                             * in the xorg.conf, then move the xorg.conf away */
                            if (has_changed || has_xorg_conf_binary_drivers(current_devices, cards_n)) {
                                fprintf(log_handle, "System configuration has changed\n");
                                /* Remove xorg.conf */
                                remove_xorg_conf();
                            }
                            else {
                                fprintf(log_handle, "Driver not enabled or not in use\n");
                                fprintf(log_handle, "Nothing to do\n");
                            }
                        }

                    }
                }
                else if (discrete_vendor_id == AMD) {
                    fprintf(log_handle, "Discrete AMD card detected\n");

                    /* Kernel module is available */
                    if (fglrx_loaded && !radeon_loaded) {
                        /* Try to enable fglrx */
                        enable_fglrx(alternative, discrete_vendor_id, current_devices, cards_n);
                    }
                    /* Kernel module is not available */
                    else {
                        /* If both the closed kernel module and the open
                         * kernel module are loaded, then we're in trouble
                         */
                        if (fglrx_loaded && radeon_loaded) {
                            /* Fake a system change to trigger
                             * a reconfiguration
                             */
                            has_changed = 1;
                        }

                        /* See if alternatives are broken */
                        if (!alternative->mesa_enabled) {
                            /* Select mesa as a fallback */
                            fprintf(log_handle, "Kernel Module is not loaded\n");
                            status = enable_mesa();
                        }
                        else {
                            /* If the system has changed or a binary driver is still
                             * in the xorg.conf, then move the xorg.conf away */
                            if (has_changed || has_xorg_conf_binary_drivers(current_devices, cards_n)) {
                                fprintf(log_handle, "System configuration has changed\n");
                                /* Remove xorg.conf */
                                remove_xorg_conf();
                            }
                            else {
                                fprintf(log_handle, "Driver not enabled or not in use\n");
                                fprintf(log_handle, "Nothing to do\n");
                            }
                        }
                    }
                }
                else {
                    fprintf(log_handle, "Unsupported discrete card vendor: %x\n", discrete_vendor_id);
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
        }
        /* AMD */
        else if (boot_vga_vendor_id == AMD) {
            /* Either AMD+AMD hybrid system or AMD desktop APU + discrete card */
            fprintf(log_handle, "AMD IGP detected\n");
            if (discrete_vendor_id == AMD) {
                fprintf(log_handle, "Discrete AMD card detected\n");


                /* Kernel module is available */
                if (fglrx_loaded && !radeon_loaded) {
                    /* Try to enable fglrx */
                    enable_fglrx(alternative, discrete_vendor_id, current_devices, cards_n);
                }
                /* Kernel module is not available */
                else {
                    /* If both the closed kernel module and the open
                     * kernel module are loaded, then we're in trouble
                     */
                    if (fglrx_loaded && radeon_loaded) {
                        /* Fake a system change to trigger
                         * a reconfiguration
                         */
                        has_changed = 1;
                    }
                    /* See if alternatives are broken */
                    if (!alternative->mesa_enabled) {
                        /* Select mesa as a fallback */
                        fprintf(log_handle, "Kernel Module is not loaded\n");
                        status = enable_mesa();
                    }
                    else {
                        /* If the system has changed or a binary driver is still
                         * in the xorg.conf, then move the xorg.conf away */
                        if (has_changed || has_xorg_conf_binary_drivers(current_devices, cards_n)) {
                            fprintf(log_handle, "System configuration has changed\n");
                            /* Remove xorg.conf */
                            remove_xorg_conf();
                        }
                        else {
                            fprintf(log_handle, "Driver not enabled or not in use\n");
                            fprintf(log_handle, "Nothing to do\n");
                        }
                    }
                }
            }
            else if (discrete_vendor_id == NVIDIA) {
                fprintf(log_handle, "Discrete NVIDIA card detected\n");

                /* Kernel module is available */
                if (nvidia_loaded && !nouveau_loaded) {
                    /* Try to enable nvidia */
                    enable_nvidia(alternative, discrete_vendor_id, current_devices, cards_n);
                }
                /* Nvidia kernel module is not available */
                else {
                    /* See if fglrx is in use */
                    /* Kernel module is available */
                    if (fglrx_loaded && !radeon_loaded) {
                        /* Try to enable fglrx */
                        enable_fglrx(alternative, boot_vga_vendor_id, current_devices, cards_n);
                    }
                    /* Kernel module is not available */
                    else {
                        /* If both the closed kernel module and the open
                         * kernel module are loaded, then we're in trouble
                         */
                        if ((fglrx_loaded && radeon_loaded) ||
                            (nvidia_loaded && nouveau_loaded)) {
                            /* Fake a system change to trigger
                             * a reconfiguration
                             */
                            has_changed = 1;
                        }

                        /* See if alternatives are broken */
                        if (!alternative->mesa_enabled) {
                            /* Select mesa as a fallback */
                            fprintf(log_handle, "Kernel Module is not loaded\n");
                            enable_mesa();
                        }
                        else {
                            /* If the system has changed or a binary driver is still
                             * in the xorg.conf, then move the xorg.conf away */
                            if (has_changed || has_xorg_conf_binary_drivers(current_devices, cards_n)) {
                                fprintf(log_handle, "System configuration has changed\n");
                                /* Remove xorg.conf */
                                remove_xorg_conf();
                            }
                            else {
                                fprintf(log_handle, "Driver not enabled or not in use\n");
                                fprintf(log_handle, "Nothing to do\n");
                            }
                        }

                    }
                }
            }
            else {
                fprintf(log_handle, "Unsupported discrete card vendor: %x\n", discrete_vendor_id);
                fprintf(log_handle, "Nothing to do\n");
            }
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

    if (xorg_conf_file)
        free(xorg_conf_file);

    if (amd_pcsdb_file)
        free(amd_pcsdb_file);

    if (main_arch_path)
        free(main_arch_path);

    if (other_arch_path)
        free(other_arch_path);

    if (alternative) {
        if (alternative->current)
            free(alternative->current);
        free(alternative);
    }

    if (fake_alternatives_path)
        free(fake_alternatives_path);

    if (fake_dmesg_path)
        free(fake_dmesg_path);

    if (fake_modules_path)
        free(fake_modules_path);

    if (prime_settings)
        free(prime_settings);

    if (bbswitch_path)
        free(bbswitch_path);

    if (bbswitch_quirks_path)
        free(bbswitch_quirks_path);

    if (dmi_product_version_path)
        free(dmi_product_version_path);

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
