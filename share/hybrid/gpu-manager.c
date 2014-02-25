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
 * Build with `gcc -o gpu-manager gpu-manager.c $(pkg-config --cflags --libs pciaccess)`
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


#define PCI_CLASS_PREHISTORIC           0x00

#define PCI_CLASS_DISPLAY               0x03

#define PCI_CLASS_MULTIMEDIA            0x04
#define PCI_SUBCLASS_MULTIMEDIA_VIDEO   0x00

#define PCI_CLASS_PROCESSOR             0x0b
#define PCI_SUBCLASS_PROCESSOR_COPROC   0x40

#define PCIINFOCLASSES(c)                                               \
    ( (((c) & 0x00ff0000) == (PCI_CLASS_PREHISTORIC << 16))             \
      || (((c) & 0x00ff0000) == (PCI_CLASS_DISPLAY << 16))              \
      || ((((c) & 0x00ffff00)                                           \
           == ((PCI_CLASS_MULTIMEDIA << 16) | (PCI_SUBCLASS_MULTIMEDIA_VIDEO << 8)))) \
      || ((((c) & 0x00ffff00)                                           \
           == ((PCI_CLASS_PROCESSOR << 16) | (PCI_SUBCLASS_PROCESSOR_COPROC << 8)))) )

#define FILENAME_ "/var/lib/ubuntu-drivers-common/last_gfx_boot"
#define FILENAME "last_gfx_boot"

#define FORCE_LAPTOP "/etc/force-laptop"

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
static char *fake_modules_path = NULL;
static char *fake_alternatives_path = NULL;

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


/* Get the first line of the output of a command */
char* get_output(char *command) {
    int len;
    char temp[1035];
    char *output = NULL;
    FILE *pfile = NULL;
    pfile = popen(command, "r");
    if (pfile == NULL) {
        fprintf(stderr, "Failed to run command\n");
        return NULL;
    }

    if (fgets(temp, sizeof(temp), pfile) != NULL) {
        output = (char*)malloc(strlen(temp) + 1);
        if (!output) {
            pclose(pfile);
            return NULL;
        }
        strcpy(output, temp);
    }
    pclose(pfile);

    /* Remove newline */
    len = strlen(output);
    if(output[len-1] == '\n' )
       output[len-1] = 0;

    return output;
}


static void get_architecture_paths(char **main_arch_path,
                                  char **other_arch_path) {
    char *main_arch = NULL;

    main_arch = get_output("dpkg --print-architecture");
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
            return 0;
        }
        while (fgets(command, sizeof(command), pfile)) {
            if (strstr(command, pattern) != NULL) {
                alternative = strdup(command);
                break;
            }
        }
    }
    else {
        sprintf(command, "update-alternatives --list %s_gl_conf | grep %s",
                arch_path, pattern);
        alternative = get_output(command);
    }

    return alternative;
}


static char * get_current_alternative(char *master_link) {
    char *alternative = NULL;
    char command[200];
    sprintf(command, "/usr/bin/update-alternatives --query %s_gl_conf "
            "| grep \"Value:\" | sed \"s/Value: //g\"",
            master_link);
    alternative = get_output(command);

    return alternative;
}


/* Get the master link of an alternative */
static int set_alternative(char *arch_path, char *alternative) {
    int status = -1;
    char command[200];
    sprintf(command, "update-alternatives --set %s_gl_conf %s",
            arch_path, alternative);

    if (dry_run) {
        status = 1;
        fprintf(log_handle, "%s\n", command);
    }
    else {
        status = system(command);
    }

    if (!status)
        return 0;

    /* call ldconfig */
    if (dry_run)
        fprintf(log_handle, "Calling ldconfig\n");
    else
        status = system("ldconfig");

    if (!status)
        return 0;
    return 1;
}

static int select_driver(char *arch_path, char *driver) {
    int status = 0;
    char *alternative = NULL;
    alternative = get_alternative_link(arch_path, driver);

    if (alternative == NULL) {
        fprintf(log_handle, "Error: no alternative found for %s\n", driver);
    }
    else {
        /* Set the alternative */
        status = set_alternative(arch_path, alternative);
        free(alternative);
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


/* This is just for writing the BusID of the discrete
 * card
 */
static int write_to_xorg_conf(struct device **devices, int cards_n,
                              unsigned int vendor_id) {
    int i;
    FILE *pfile = NULL;
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
    pfile = fopen(xorg_conf_file, "w");
    if (pfile == NULL) {
        fprintf(log_handle, "I couldn't open %s for writing.\n",
                xorg_conf_file);
        return 0;
    }

    for(i = 0; i < cards_n; i++) {
        if (devices[i]->vendor_id == INTEL) {
            fprintf(pfile,
               "Section \"Device\"\n"
               "    Identifier \"Default Card %d\"\n"
               "    Driver \"intel\"\n"
               "    Option \"AccelMethod\" \"uxa\"\n"
               "    BusID \"PCI:%d@%d:%d:%d\"\n"
               "EndSection\n\n",
               i,
               (int)(devices[i]->bus),
               (int)(devices[i]->domain),
               (int)(devices[i]->dev),
               (int)(devices[i]->func));
        }
        else if (devices[i]->vendor_id == AMD) {
            fprintf(pfile,
               "Section \"Device\"\n"
               "    Identifier \"Default Card %d\"\n"
               "    Driver \"fglrx\"\n"
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


/* Check AMD's configuration file is the discrete GPU
 * is set to be disabled
 */
static int is_pxpress_dgpu_disabled() {
    int disabled = 0;
    char line[4096];
    FILE *file;
    struct stat stbuf;

    /* If file doesn't exist */
    if (stat(amd_pcsdb_file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", amd_pcsdb_file);
        return 0;
    }
    /* If file is empty */
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size) {
        fprintf(log_handle, "%s is empty\n", amd_pcsdb_file);
        return 0;
    }


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


/* Check xorg.conf to see if it's all properly set */
static int check_pxpress_xorg_conf(struct device **devices,
                                   int cards_n) {
    int failure = 0;
    int i;
    int intel_matches = 0;
    int amd_matches = 0;
    int x_options_matches = 0;
    char line[4096];
    char intel_bus_id[100];
    char amd_bus_id[100];
    FILE *file;
    struct stat stbuf;

    /* If file doesn't exist */
    if (stat(xorg_conf_file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", xorg_conf_file);
        return 0;
    }
    /* If file is empty */
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size) {
        fprintf(log_handle, "%s is empty\n", xorg_conf_file);
        return 0;
    }


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
            sprintf(amd_bus_id, "\"PCI:%d@%d:%d:%d\"",
                                (int)(devices[i]->bus),
                                (int)(devices[i]->domain),
                                (int)(devices[i]->dev),
                                (int)(devices[i]->func));
        }
    }

    while (fgets(line, sizeof(line), file)) {
        /* Ignore comments */
        if (strstr(line, "#") == NULL) {
            if (strstr(line, intel_bus_id) != NULL) {
                intel_matches += 1;
            }
            else if (strstr(line, amd_bus_id) != NULL) {
                amd_matches += 1;
            }
            /* It has to be either intel or fglrx */
            else if (istrstr(line, "Driver") != NULL &&
                     istrstr(line, "Option") == NULL) {
                if (istrstr(line, "intel") == NULL &&
                    istrstr(line, "fglrx") == NULL) {
                    failure = 1;
                    fprintf(log_handle, "Unsupported driver in "
                            "xorg.conf. Path: %s\n", xorg_conf_file);
                    fprintf(log_handle, "line: %s\n", line);
                    break;
                }

            }
            else if (istrstr(line, "AccelMethod") != NULL &&
                     istrstr(line, "UXA") != NULL) {
                x_options_matches += 1;
            }
        }
    }

    fclose(file);

    return (intel_matches == 1 && amd_matches == 1 &&
            x_options_matches > 0 && !failure);
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
    struct stat stbuf;

    /* If file doesn't exist */
    if (stat(xorg_conf_file, &stbuf) == -1) {
        fprintf(log_handle, "can't access %s\n", xorg_conf_file);
        return 0;
    }
    /* If file is empty */
    if ((stbuf.st_mode & S_IFMT) && ! stbuf.st_size) {
        fprintf(log_handle, "%s is empty\n", xorg_conf_file);
        return 0;
    }


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


static int get_vars(FILE *file, struct device **devices, int num) {
    int status;

    devices[num] = (struct device*) malloc(sizeof(struct device));

    if (!devices[num])
        return EOF;

    status = fscanf(file, "%04x:%04x;%04x:%02x:%02x:%d;%d\n",
                    &devices[num]->vendor_id,
                    &devices[num]->device_id,
                    &devices[num]->domain,
                    &devices[num]->bus,
                    &devices[num]->dev,
                    &devices[num]->func,
                    &devices[num]->boot_vga);

    if (status == EOF)
        free(devices[num]);

    return status;
}


static int read_data_from_file(struct device **devices,
                               int *cards_number,
                               char *filename) {
    /* Read from last boot gfx */
    int i;
    FILE *pfile = NULL;
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
        while (get_vars(pfile, devices, *cards_number) != EOF) {
            *cards_number += 1;
        }
    }

    fclose(pfile);
    return 1;
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


static int is_laptop (void) {
    /* We only support laptops by default,
     * you can override this check by creating
     * the /etc/force-pxpress file
     */
    if (is_file(FORCE_LAPTOP)) {
        fprintf(log_handle, "Forcing laptop mode as per %s\n", FORCE_LAPTOP);
        return 1;
    }
    else {
        if (! is_dir_empty("/sys/class/power_supply/") &&
            is_dir("/proc/acpi/button/lid"))
            return 1;
        else
            return 0;
    }
}


static int is_alternative_in_use(char *alternative, char *pattern) {
    /* Avoid getting false positives when looking for nvidia
     * and finding nvidia-*-prime instead
     */
    if ((strcmp(pattern, "nvidia") == 0) &&
        (strstr(alternative, "prime") != NULL))
        return 0;
    return (strstr(alternative, pattern) != NULL);
}


static int move_xorg_conf(void) {
    int status;
    char backup[200];
    char buffer[80];
    time_t rawtime;
    struct tm *info;

    time(&rawtime);
    info = localtime(&rawtime);

    strftime(buffer, 80, "%m%d%Y", info);
    sprintf(backup, "%s.%s", xorg_conf_file, buffer);

    fprintf(log_handle, "Moving %s to %s\n", xorg_conf_file, backup);

    status = rename(xorg_conf_file, backup);
    if (!status)
        status = unlink(xorg_conf_file);
        if (!status)
            return 0;
        else
            return 1;

    return 1;
}


int main(int argc, char *argv[]) {

    int opt, i;
    char *fake_lspci_file = NULL;
    char *new_boot_file = NULL;

    static int fake_laptop;

    int has_intel = 0, has_amd = 0, has_nvidia = 0;
    int has_changed = 0;
    int has_moved_xorg_conf = 0;
    int nvidia_loaded = 0, fglrx_loaded = 0,
        intel_loaded = 0, radeon_loaded = 0,
        nouveau_loaded = 0;
    int laptop = 0;
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
    char *alternative = NULL;
    char *main_arch_path = NULL;
    char *other_arch_path = NULL;
    int nvidia_enabled = 0, fglrx_enabled = 0, mesa_enabled = 0;
    int pxpress_enabled = 0, prime_enabled = 0;

    while (1) {
        static struct option long_options[] =
        {
        /* These options set a flag. */
        {"dry-run", no_argument,     &dry_run, 1},
        {"fake-laptop", no_argument, &fake_laptop, 1},
        {"fake-desktop", no_argument, &fake_laptop, 0},
        /* These options don't set a flag.
          We distinguish them by their indices. */
        /*
        {"",  no_argument,       0, 'a'},
        {"log",  no_argument,       0, 'l'},
        */
        {"log",  required_argument, 0, 'l'},
        {"fake-lspci",  required_argument, 0, 'f'},
        {"last-boot-file", required_argument, 0, 'b'},
        {"new-boot-file", required_argument, 0, 'n'},
        {"xorg-conf-file", required_argument, 0, 'x'},
        {"amd-pcsdb-file", required_argument, 0, 'd'},
        {"fake-alternative", required_argument, 0, 'a'},
        {"fake-modules-path", required_argument, 0, 'm'},
        {"fake-alternatives-path", required_argument, 0, 'p'},
        {0, 0, 0, 0}
        };
        /* getopt_long stores the option index here. */
        int option_index = 0;

        opt = getopt_long (argc, argv, "lsf:::",
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
                log_file = (char*)malloc(strlen(optarg) + 1);
                if (log_file)
                    strcpy(log_file, optarg);
                else
                    abort();
                break;
            case 'b':
                /* printf("option -b with value '%s'\n", optarg); */
                last_boot_file = (char*)malloc(strlen(optarg) + 1);
                if (last_boot_file)
                    strcpy(last_boot_file, optarg);
                else
                    abort();
                break;
            case 'n':
                /* printf("option -n with value '%s'\n", optarg); */
                new_boot_file = (char*)malloc(strlen(optarg) + 1);
                if (new_boot_file)
                    strcpy(new_boot_file, optarg);
                else
                    abort();
                break;
            case 'f':
                /* printf("option -f with value '%s'\n", optarg); */
                fake_lspci_file = (char*)malloc(strlen(optarg) + 1);
                if (fake_lspci_file)
                    strcpy(fake_lspci_file, optarg);
                else
                    abort();
                break;
            case 'x':
                /* printf("option -x with value '%s'\n", optarg); */
                xorg_conf_file = (char*)malloc(strlen(optarg) + 1);
                if (xorg_conf_file)
                    strcpy(xorg_conf_file, optarg);
                else
                    abort();
                break;
            case 'd':
                /* printf("option -x with value '%s'\n", optarg); */
                amd_pcsdb_file = (char*)malloc(strlen(optarg) + 1);
                if (amd_pcsdb_file)
                    strcpy(amd_pcsdb_file, optarg);
                else
                    abort();
                break;
            case 'a':
                /* printf("option -a with value '%s'\n", optarg); */
                alternative = (char*)malloc(strlen(optarg) + 1);
                if (alternative)
                    strcpy(alternative, optarg);
                else
                    abort();
                break;
            case 'm':
                /* printf("option -m with value '%s'\n", optarg); */
                fake_modules_path = (char*)malloc(strlen(optarg) + 1);
                if (fake_modules_path)
                    strcpy(fake_modules_path, optarg);
                else
                    abort();
                break;
            case 'p':
                /* printf("option -p with value '%s'\n", optarg); */
                fake_alternatives_path = (char*)malloc(strlen(optarg) + 1);
                if (fake_alternatives_path)
                    strcpy(fake_alternatives_path, optarg);
                else
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

    /* TODO: require arguments and abort if they're not available */

    if (log_file)
        fprintf(log_handle, "log_file: %s\n", log_file);

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
        xorg_conf_file = (char*)malloc(strlen("/etc/X11/xorg.conf") + 1);
        if (xorg_conf_file) {
            strcpy(xorg_conf_file, "/etc/X11/xorg.conf");
        }
        else {
            fprintf(log_handle, "Couldn't allocate xorg_conf_file\n");
            goto end;
        }

    }

    if (amd_pcsdb_file)
        fprintf(log_handle, "amd_pcsdb_file file: %s\n", amd_pcsdb_file);
    else {
        amd_pcsdb_file = (char*)malloc(strlen("/etc/ati/amdpcsdb") + 1);
        if (amd_pcsdb_file) {
            strcpy(amd_pcsdb_file, "/etc/ati/amdpcsdb");
        }
        else {
            fprintf(log_handle, "Couldn't allocate amd_pcsdb_file\n");
            goto end;
        }
    }

    /* Either simulate or check if dealing with a laptop */
    if (fake_lspci_file)
        laptop = fake_laptop;
    else
        laptop = is_laptop();

    fprintf(log_handle, "Is laptop? %s\n", (laptop ? "yes" : "no"));

    nvidia_loaded = is_module_loaded("nvidia");
    fglrx_loaded = is_module_loaded("fglrx");
    intel_loaded = is_module_loaded("i915") || is_module_loaded("i810");
    radeon_loaded = is_module_loaded("radeon");
    nouveau_loaded = is_module_loaded("nouveau");

    fprintf(log_handle, "Is nvidia loaded? %s\n", (nvidia_loaded ? "yes" : "no"));
    fprintf(log_handle, "Is fglrx loaded? %s\n", (fglrx_loaded ? "yes" : "no"));
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
                fprintf(log_handle, "BusID \"PCI:%x:%x:%x\"\n", info->bus, info->dev, info->func);
                fprintf(log_handle, "Is boot vga? %s\n", (pci_device_is_boot_vga(info) ? "yes" : "no"));

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
                    current_devices[cards_n] = (struct device*) malloc(sizeof(struct device));
                    current_devices[cards_n]->boot_vga = pci_device_is_boot_vga(info);
                    current_devices[cards_n]->vendor_id = info->vendor_id;
                    current_devices[cards_n]->device_id = info->device_id;
                    current_devices[cards_n]->bus = info->bus;
                    current_devices[cards_n]->dev = info->dev;
                    current_devices[cards_n]->func = info->func;
                }
                else {
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


    /* TODO: disable if Bumblebee is in use */

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
        alternative = get_current_alternative(main_arch_path);

    if (!alternative) {
        fprintf(stderr, "Error: no alternative found\n");
        goto end;
    }

    fprintf(log_handle, "Current alternative: %s\n", alternative);

    nvidia_enabled = is_alternative_in_use(alternative, "nvidia");
    fglrx_enabled = is_alternative_in_use(alternative, "fglrx");
    mesa_enabled = is_alternative_in_use(alternative, "mesa");
    pxpress_enabled = is_alternative_in_use(alternative, "pxpress");
    prime_enabled = is_alternative_in_use(alternative, "prime");

    fprintf(log_handle, "Is nvidia enabled? %s\n", nvidia_enabled ? "yes" : "no");
    fprintf(log_handle, "Is fglrx enabled? %s\n", fglrx_enabled ? "yes" : "no");
    fprintf(log_handle, "Is mesa enabled? %s\n", mesa_enabled ? "yes" : "no");
    fprintf(log_handle, "Is pxpress enabled? %s\n", pxpress_enabled ? "yes" : "no");
    fprintf(log_handle, "Is prime enabled? %s\n", prime_enabled ? "yes" : "no");

    if (has_changed)
        fprintf(log_handle, "System configuration has changed\n");

    if (cards_n == 1) {
        fprintf(log_handle, "Single card detected\n");

        /* Get data about the boot_vga card */
        get_boot_vga(current_devices, cards_n,
                     &boot_vga_vendor_id,
                     &boot_vga_device_id);

        if (boot_vga_vendor_id == INTEL) {
            if (!mesa_enabled) {
                /* Select mesa */
                fprintf(log_handle, "Selecting mesa\n");
                status = select_driver(main_arch_path, "mesa");
                /* select_driver(other_arch_path, "mesa"); */

                /* Remove xorg.conf */
                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                move_xorg_conf();
                has_moved_xorg_conf = 1;
            }
            else {
                fprintf(log_handle, "Nothing to do\n");
            }
        }
        else if (boot_vga_vendor_id == AMD) {
            /* if fglrx is loaded enable fglrx alternative */
            if (fglrx_loaded) {
                if (!fglrx_enabled) {
                    /* Select fglrx */
                    fprintf(log_handle, "Selecting fglrx\n");
                    status = select_driver(main_arch_path, "fglrx");
                    /* select_driver(other_arch_path, "fglrx"); */

                    /* Remove xorg.conf */
                    fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                    move_xorg_conf();
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Driver is already loaded and enabled\n");
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
            else {
                /* Select mesa as a fallback */
                fprintf(log_handle, "Kernel Module is not loaded\n");
                if (!mesa_enabled) {
                    fprintf(log_handle, "Selecting mesa\n");
                    status = select_driver(main_arch_path, "mesa");
                    /* select_driver(other_arch_path, "mesa"); */

                    /* Remove xorg.conf */
                    fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                    move_xorg_conf();
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
        }
        else if (boot_vga_vendor_id == NVIDIA) {
            /* if nvidia is loaded enable nvidia alternative */
            if (nvidia_loaded) {
                if (!nvidia_enabled) {
                    /* Select nvidia */
                    fprintf(log_handle, "Selecting nvidia\n");
                    status = select_driver(main_arch_path, "nvidia");
                    /* select_driver(other_arch_path, "nvidia"); */

                    /* Remove xorg.conf */
                    fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                    move_xorg_conf();
                    has_moved_xorg_conf = 1;
                }
                else {
                    fprintf(log_handle, "Driver is already loaded and enabled\n");
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
            else {
                /* Select mesa as a fallback */
                fprintf(log_handle, "Kernel Module is not loaded\n");
                if (!mesa_enabled) {
                    fprintf(log_handle, "Selecting mesa\n");
                    status = select_driver(main_arch_path, "mesa");
                    /* select_driver(other_arch_path, "mesa"); */

                    /* Remove xorg.conf */
                    fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                    move_xorg_conf();
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
                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                move_xorg_conf();
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
            if (laptop && intel_loaded && fglrx_loaded && !radeon_loaded) {
                /* See if the discrete GPU is disabled */
                if (is_pxpress_dgpu_disabled()) {
                    if (!pxpress_enabled) {
                        fprintf(log_handle, "Selecting pxpress\n");
                        status = select_driver(main_arch_path, "pxpress");
                    }
                    else {
                        fprintf(log_handle, "Driver is already loaded and enabled\n");
                        status = 1;
                    }
                }
                else {
                    if (!fglrx_enabled) {
                        fprintf(log_handle, "Selecting fglrx\n");
                        status = select_driver(main_arch_path, "fglrx");
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
                        fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                        move_xorg_conf();
                        /* Write xorg.conf */
                        fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
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
                    select_driver(main_arch_path, "mesa");
                    /* select_driver(other_arch_path, "mesa"); */
                    /* Remove xorg.conf */
                    fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                    move_xorg_conf();
                }
            }
            /* NVIDIA Optimus */
            else if (laptop && (intel_loaded && !nouveau_loaded &&
                                (nvidia_enabled || prime_enabled ||
                                 nvidia_loaded))) {
                /* Hybrid graphics
                 * No need to do anything, as either nvidia-prime or
                 * fglrx-pxpress will take over.
                 */
                fprintf(log_handle, "Intel hybrid laptop - nothing to do\n");
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
                    if (nvidia_loaded) {
                        /* Alternative not in use */
                        if (!nvidia_enabled) {
                            /* Select nvidia */
                            fprintf(log_handle, "Selecting nvidia\n");
                            status = select_driver(main_arch_path, "nvidia");
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
                            if (!check_vendor_bus_id_xorg_conf(current_devices, cards_n,
                                                               discrete_vendor_id, "nvidia")) {
                                fprintf(log_handle, "Check failed\n");

                                /* Remove xorg.conf */
                                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                                move_xorg_conf();
                                /* Write xorg.conf */
                                fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
                                write_to_xorg_conf(current_devices, cards_n, discrete_vendor_id);
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
                            select_driver(main_arch_path, "mesa");
                            /* select_driver(other_arch_path, "mesa"); */
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                    }
                    /* Kernel module is not available */
                    else {
                        /* See if alternatives are broken */
                        if (!mesa_enabled) {
                            /* Select mesa as a fallback */
                            fprintf(log_handle, "Kernel Module is not loaded\n");
                            fprintf(log_handle, "Selecting mesa\n");
                            status = select_driver(main_arch_path, "mesa");
                            /* select_driver(other_arch_path, "mesa"); */
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                        else {
                            if (has_changed) {
                                fprintf(log_handle, "System configuration has changed\n");
                                /* Remove xorg.conf */
                                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                                move_xorg_conf();
                            }
                            else {
                                fprintf(log_handle, "Driver not enabled or not in use\n");
                                fprintf(log_handle, "Nothing to do\n");
                            }
                        }

                    }
#if 0
                    if (nvidia_loaded && nvidia_enabled) {
                        fprintf(log_handle, "Driver enabled and in use\n");
                        /* TODO: If xorg.conf exists, make sure it contains
                         * the right BusId and NO NOUVEAU or FGLRX. If it doesn't, create a
                         * xorg.conf from scratch */
                        fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
                        write_to_xorg_conf(discrete_bus, discrete_dev, discrete_func);
                    }
                    else {
                        fprintf(log_handle, "Driver not enabled or not in use\n");
                        fprintf(log_handle, "Nothing to do\n");
                    }
#endif
                }
                else if (discrete_vendor_id == AMD) {
                    fprintf(log_handle, "Discrete AMD card detected\n");

                    /* Kernel module is available */
                    if (fglrx_loaded) {
                        /* Alternative not in use */
                        if (!fglrx_enabled) {
                            /* Select nvidia */
                            fprintf(log_handle, "Selecting fglrx\n");
                            status = select_driver(main_arch_path, "fglrx");
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
                            if (!check_vendor_bus_id_xorg_conf(current_devices, cards_n,
                                                               discrete_vendor_id, "fglrx")) {
                                fprintf(log_handle, "Check failed\n");

                                /* Remove xorg.conf */
                                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                                move_xorg_conf();
                                /* Write xorg.conf */
                                fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
                                write_to_xorg_conf(current_devices, cards_n, discrete_vendor_id);
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
                            select_driver(main_arch_path, "mesa");
                            /* select_driver(other_arch_path, "mesa"); */
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                    }
                    /* Kernel module is not available */
                    else {
                        /* See if alternatives are broken */
                        if (!mesa_enabled) {
                            /* Select mesa as a fallback */
                            fprintf(log_handle, "Kernel Module is not loaded\n");
                            fprintf(log_handle, "Selecting mesa\n");
                            status = select_driver(main_arch_path, "mesa");
                            /* select_driver(other_arch_path, "mesa"); */
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                        else {
                            if (has_changed) {
                                fprintf(log_handle, "System configuration has changed\n");
                                /* Remove xorg.conf */
                                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                                move_xorg_conf();
                            }
                            else {
                                fprintf(log_handle, "Driver not enabled or not in use\n");
                                fprintf(log_handle, "Nothing to do\n");
                            }
                        }
                    }


#if 0
                    if (fglrx_loaded && fglrx_enabled) {
                        fprintf(log_handle, "Driver enabled and in use\n");
                        /* TODO: If xorg.conf exists, make sure it contains
                         * the right BusId and fglrx. If it doesn't, create a
                         * xorg.conf from scratch using aticonfig */
                        fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);

                        /* Call aticonfig */
                        enable_all_amds();
                    }
                    else {
                        fprintf(log_handle, "Driver not enabled or not in use\n");
                        fprintf(log_handle, "Nothing to do\n");
                    }
#endif
                }
                else {
                    fprintf(log_handle, "Unsupported discrete card vendor: %x\n", discrete_vendor_id);
                    fprintf(log_handle, "Nothing to do\n");
                }
            }
        }
        /* AMD */
        else if (boot_vga_vendor_id == AMD) {
            /* Either AMD+AMD hybrid laptop or AMD desktop APU + discrete card */
            fprintf(log_handle, "AMD IGP detected\n");
            if (discrete_vendor_id == AMD) {
                fprintf(log_handle, "Discrete AMD card detected\n");


                /* Kernel module is available */
                if (fglrx_loaded) {
                    /* Alternative not in use */
                    if (!fglrx_enabled) {
                        /* Select nvidia */
                        fprintf(log_handle, "Selecting fglrx\n");
                        status = select_driver(main_arch_path, "fglrx");
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
                        if (!check_vendor_bus_id_xorg_conf(current_devices, cards_n,
                                                           discrete_vendor_id, "fglrx")) {
                            fprintf(log_handle, "Check failed\n");

                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                            /* Write xorg.conf */
                            fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
                            write_to_xorg_conf(current_devices, cards_n, discrete_vendor_id);
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
                        select_driver(main_arch_path, "mesa");
                        /* select_driver(other_arch_path, "mesa"); */
                        /* Remove xorg.conf */
                        fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                        move_xorg_conf();
                    }
                }
                /* Kernel module is not available */
                else {
                    /* See if alternatives are broken */
                    if (!mesa_enabled) {
                        /* Select mesa as a fallback */
                        fprintf(log_handle, "Kernel Module is not loaded\n");
                        fprintf(log_handle, "Selecting mesa\n");
                        status = select_driver(main_arch_path, "mesa");
                        /* select_driver(other_arch_path, "mesa"); */
                        /* Remove xorg.conf */
                        fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                        move_xorg_conf();
                    }
                    else {
                        if (has_changed) {
                            fprintf(log_handle, "System configuration has changed\n");
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                        else {
                            fprintf(log_handle, "Driver not enabled or not in use\n");
                            fprintf(log_handle, "Nothing to do\n");
                        }
                    }
                }
            }
            else if (discrete_vendor_id == NVIDIA) {
                fprintf(log_handle, "Discrete AMD card detected\n");

                /* Kernel module is available */
                if (nvidia_loaded) {
                    /* Alternative not in use */
                    if (!nvidia_enabled) {
                        /* Select nvidia */
                        fprintf(log_handle, "Selecting nvidia\n");
                        status = select_driver(main_arch_path, "nvidia");
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
                        if (!check_vendor_bus_id_xorg_conf(current_devices, cards_n,
                                                           discrete_vendor_id, "nvidia")) {
                            fprintf(log_handle, "Check failed\n");

                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                            /* Write xorg.conf */
                            fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
                            write_to_xorg_conf(current_devices, cards_n, discrete_vendor_id);
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
                        select_driver(main_arch_path, "mesa");
                        /* select_driver(other_arch_path, "mesa"); */
                        /* Remove xorg.conf */
                        fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                        move_xorg_conf();
                    }
                }
                /* Nvidia kernel module is not available */
                else {
                    /* See if fglrx is in use */
                    /* Kernel module is available */
                    if (fglrx_loaded) {
                        /* Alternative not in use */
                        if (!fglrx_enabled) {
                            /* Select nvidia */
                            fprintf(log_handle, "Selecting fglrx\n");
                            status = select_driver(main_arch_path, "fglrx");
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
                            if (!check_vendor_bus_id_xorg_conf(current_devices, cards_n,
                                                               boot_vga_vendor_id, "fglrx")) {
                                fprintf(log_handle, "Check failed\n");

                                /* Remove xorg.conf */
                                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                                move_xorg_conf();
                                /* Write xorg.conf */
                                fprintf(log_handle, "Regenerating xorg.conf. Path: %s\n", xorg_conf_file);
                                write_to_xorg_conf(current_devices, cards_n, discrete_vendor_id);
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
                            select_driver(main_arch_path, "mesa");
                            /* select_driver(other_arch_path, "mesa"); */
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                    }
                    /* Kernel module is not available */
                    else {
                        /* See if alternatives are broken */
                        if (!mesa_enabled) {
                            /* Select mesa as a fallback */
                            fprintf(log_handle, "Kernel Module is not loaded\n");
                            fprintf(log_handle, "Selecting mesa\n");
                            status = select_driver(main_arch_path, "mesa");
                            /* select_driver(other_arch_path, "mesa"); */
                            /* Remove xorg.conf */
                            fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                            move_xorg_conf();
                        }
                        else {
                            if (has_changed) {
                                fprintf(log_handle, "System configuration has changed\n");
                                /* Remove xorg.conf */
                                fprintf(log_handle, "Removing xorg.conf. Path: %s\n", xorg_conf_file);
                                move_xorg_conf();
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

    if (fake_alternatives_path)
        free(fake_alternatives_path);

    if (fake_modules_path)
        free(fake_modules_path);

    if (alternative)
        free(alternative);

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
