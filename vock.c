#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <libgen.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <linux/kcov.h>
#define COVER_SZ        (64 << 10)
static int kcov_remote_enable(int *fdp, unsigned long **areap)
{
	int ret;
	struct kcov_remote_arg arg;
	*fdp = open("/sys/kernel/debug/kcov", O_RDWR);
	if (*fdp == -1) {
		perror("kcov: remote open failed");
		return -1;
	}
	ret = ioctl(*fdp, KCOV_INIT_TRACE, COVER_SZ);
	if (ret) {
		perror("kcov: remote init failed");
		return -1;
	}
	*areap = mmap(NULL, COVER_SZ * sizeof(unsigned long),
		      PROT_READ | PROT_WRITE, MAP_SHARED, *fdp, 0);
	if (*areap == (unsigned long *)MAP_FAILED) {
		perror("kcov: remote mmap failed");
		return -1;
	}
	memset(&arg, 0, sizeof(arg));
	arg.trace_mode = KCOV_TRACE_PC;
	arg.area_size = COVER_SZ;
	arg.common_handle = kcov_remote_handle(0x00ULL << 56, getpid());
	ret = ioctl(*fdp, KCOV_REMOTE_ENABLE, &arg);
	if (ret) {
		perror("kcov: remote enable failed");
		return -1;
	}
	fprintf(stderr, "kcov: remote coverage enabled\n");
	return 0;
}
static void write_remote_log(unsigned long *area)
{
	FILE *f;
	unsigned long n, i;
	f = fopen("remote_coverage.log", "w");
	if (!f) {
		perror("kcov: fopen remote_coverage.log failed");
		return;
	}
	n = __atomic_load_n(&area[0], __ATOMIC_RELAXED);
	for (i = 0; i < n; i++)
		fprintf(f, "0x%lx\n", area[i + 1]);
	fclose(f);
}
static int run_report(const char *report_path,
		      const char *kernel_src,
		      const char *vmlinux,
		      const char *filter,
		      int ctx_after, int ctx_before)
{
	char *argv_exec[24];
	int idx = 0;
	pid_t pid;
	int status;
	char a_buf[16], b_buf[16];
	argv_exec[idx++] = (char *)"python3";
	argv_exec[idx++] = (char *)report_path;
	if (kernel_src) {
		argv_exec[idx++] = (char *)"--kernel-src";
		argv_exec[idx++] = (char *)kernel_src;
	}
	if (vmlinux) {
		argv_exec[idx++] = (char *)"--vmlinux";
		argv_exec[idx++] = (char *)vmlinux;
	}
	if (filter) {
		argv_exec[idx++] = (char *)"--filter";
		argv_exec[idx++] = (char *)filter;
	}
	if (ctx_after >= 0) {
		snprintf(a_buf, sizeof(a_buf), "%d", ctx_after);
		argv_exec[idx++] = (char *)"-A";
		argv_exec[idx++] = a_buf;
	}
	if (ctx_before >= 0) {
		snprintf(b_buf, sizeof(b_buf), "%d", ctx_before);
		argv_exec[idx++] = (char *)"-B";
		argv_exec[idx++] = b_buf;
	}
	argv_exec[idx] = NULL;
	pid = fork();
	if (pid == 0) {
		execvp("python3", argv_exec);
		perror("report: execvp failed");
		_exit(127);
	} else if (pid < 0) {
		perror("report: fork failed");
		return -1;
	}
	if (waitpid(pid, &status, 0) < 0) {
		perror("report: waitpid failed");
		return -1;
	}
	return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
static int run_kcov_mode(int argc, char *argv[], int cmd_idx,
			 const char *kernel_src, const char *vmlinux,
			 const char *filter, int ctx_after, int ctx_before)
{
	char exe_path[1024];
	char *exe_dir;
	char preload_path[2048];
	char report_path[2048];
	ssize_t nread;
	int rfd = -1;
	unsigned long *rarea = (unsigned long *)MAP_FAILED;
	pid_t pid;
	int status, ret;
	(void)argc;
	nread = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
	if (nread == -1) {
		perror("readlink failed");
		return 1;
	}
	exe_path[nread] = '\0';
	exe_dir = dirname(exe_path);
	snprintf(preload_path, sizeof(preload_path), "%s/mode/kcov.so", exe_dir);
	ret = kcov_remote_enable(&rfd, &rarea);
	if (ret) {
		fprintf(stderr, "kcov: remote setup failed\n");
		return 1;
	}
	pid = fork();
	if (pid == 0) {
		setenv("LD_PRELOAD", preload_path, 1);
		execvp(argv[cmd_idx], &argv[cmd_idx]);
		perror("target: execvp failed");
		_exit(127);
	} else if (pid < 0) {
		perror("target: fork failed");
		return 1;
	}
	if (waitpid(pid, &status, 0) < 0) {
		perror("target: waitpid failed");
		return 1;
	}
	write_remote_log(rarea);
	ioctl(rfd, KCOV_DISABLE, 0);
	munmap(rarea, COVER_SZ * sizeof(unsigned long));
	close(rfd);
	fprintf(stderr, "[vock] generating report\n");
	snprintf(report_path, sizeof(report_path), "%s/output.py", exe_dir);
	ret = run_report(report_path, kernel_src, vmlinux, filter, ctx_after, ctx_before);
	if (ret)
		fprintf(stderr, "report: exit code %d\n", ret);
	return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
int main(int argc, char *argv[])
{
	char *kernel_src = NULL;
	char *vmlinux = NULL;
	char *filter = NULL;
	int ctx_after = -1, ctx_before = -1;
	int cmd_idx = -1;
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "selftest")) {
			char exe_path[1024], selftest_path[2048];
			char *dir;
			ssize_t n = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
			if (n == -1) { perror("readlink"); return 1; }
			exe_path[n] = '\0';
			dir = dirname(exe_path);
			snprintf(selftest_path, sizeof(selftest_path), "%s/selftest/run.py", dir);
			char *new_argv[64];
			int ai = 0;
			new_argv[ai++] = "python3";
			new_argv[ai++] = selftest_path;
			for (int j = i + 1; j < argc && ai < 62; j++)
				new_argv[ai++] = argv[j];
			new_argv[ai] = NULL;
			execv("/usr/bin/python3", new_argv);
			execvp("python3", new_argv);
			perror("selftest: exec failed");
			return 1;
		} else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
			fprintf(stderr,
"vock — kernel code coverage via KCOV\n"
"\n"
"usage: vock [OPTIONS] <cmd> [args...]\n"
"       vock selftest [--help]\n"
"\n"
"Runs <cmd> under KCOV remote coverage (needs CONFIG_KCOV), then\n"
"generates coverage.html from the collected kernel PCs.\n"
"\n"
"options:\n"
"  --kernel-src PATH   kernel source for coverage report\n"
"  --vmlinux FILE      vmlinux with debug info\n"
"  --filter KW         filter coverage report to matching paths\n"
"  -A N, -B N          context lines in coverage report\n"
"\n"
"examples:\n"
"  vock /bin/ls /tmp                        kernel coverage (KCOV)\n"
"  vock --kernel-src ~/linux /bin/ip addr   coverage with source report\n"
			);
			return 0;
		} else if (!strcmp(argv[i], "--kernel-src") && i + 1 < argc) {
			kernel_src = argv[++i];
		} else if (!strcmp(argv[i], "--vmlinux") && i + 1 < argc) {
			vmlinux = argv[++i];
		} else if (!strcmp(argv[i], "--filter") && i + 1 < argc) {
			filter = argv[++i];
		} else if (!strcmp(argv[i], "-A") && i + 1 < argc) {
			ctx_after = atoi(argv[++i]);
		} else if (!strcmp(argv[i], "-B") && i + 1 < argc) {
			ctx_before = atoi(argv[++i]);
		} else {
			cmd_idx = i;
			break;
		}
	}
	if (cmd_idx == -1) {
		fprintf(stderr,
			"usage: vock [--kernel-src PATH] [--vmlinux FILE] <cmd> [args...]\n"
			"       vock selftest [--help]\n"
			"       vock --help\n");
		exit(1);
	}
	if (geteuid() != 0) {
		fprintf(stderr,
			"error: kcov requires root privileges\n"
			"  vock %s\n", argv[cmd_idx]);
		return 1;
	}
	return run_kcov_mode(argc, argv, cmd_idx, kernel_src, vmlinux, filter,
			     ctx_after, ctx_before);
}
