// =====================================================================
//  宜小智工作台 —— 一键启动器（Windows 桌面程序）
//
//  双击这个 EXE 就能把整套工作台跑起来，不用记 PowerShell 命令。
//  它做三件事：
//    1. 检查服务是不是已经在跑 —— 已经在跑就直接打开网页，不重复拉起
//    2. 没在跑就调用 start-all.ps1 起服务，实时把进度显示在窗口里
//    3. 提供「停止服务」，让整棵进程树干净退出（端口全部释放）
//
//  编译器：Windows 自带的 .NET Framework csc.exe，不依赖 VS / .NET SDK。
//  用法：build-launcher.ps1 会自动调用它。
// =====================================================================
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal static class YXZLauncher
{
    private const int BackendPortStart = 8100;
    private const int BackendPortEnd = 8120;
    private const int FrontendPortStart = 5199;
    private const int FrontendPortEnd = 5220;

    private static string appRoot;
    private static int frontendPort = -1;
    private static int backendPort = -1;
    private static Process running;
    private static readonly StringBuilder log = new StringBuilder();

    [STAThread]
    private static void Main()
    {
        try { Application.EnableVisualStyles(); } catch { }
        Application.SetCompatibleTextRenderingDefault(false);

        appRoot = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        Application.Run(new LauncherForm());
    }

    private sealed class LauncherForm : Form
    {
        private readonly Label status = new Label();
        private readonly Label address = new Label();
        private readonly TextBox output = new TextBox();
        private readonly Button openButton = new Button();
        private readonly Button stopButton = new Button();
        private readonly Button restartButton = new Button();
        private readonly ProgressBar bar = new ProgressBar();

        public LauncherForm()
        {
            Text = "宜小智工作台";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            ClientSize = new Size(560, 430);
            StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Microsoft YaHei UI", 9F);
            BackColor = Color.FromArgb(248, 250, 252);

            var title = new Label
            {
                Text = "宜小智 · 个性化制造工作台",
                Font = new Font("Microsoft YaHei UI", 14F, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                AutoSize = true,
                Location = new Point(22, 18),
            };

            status.Text = "正在检查服务状态…";
            status.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
            status.ForeColor = Color.FromArgb(37, 99, 235);
            status.AutoSize = true;
            status.Location = new Point(22, 58);

            address.Text = "";
            address.ForeColor = Color.FromArgb(100, 116, 139);
            address.AutoSize = true;
            address.Location = new Point(22, 82);

            bar.Location = new Point(22, 106);
            bar.Size = new Size(516, 8);
            bar.Style = ProgressBarStyle.Continuous;

            Configure(openButton, "打开宜小智", 22, new Size(150, 36));
            Configure(stopButton, "停止服务", 182, new Size(120, 36));
            Configure(restartButton, "重新启动", 312, new Size(120, 36));
            openButton.Click += (s, e) => OpenBrowser();
            stopButton.Click += (s, e) => StopServices();
            restartButton.Click += (s, e) => RestartServices();

            output.Multiline = true;
            output.ReadOnly = true;
            output.ScrollBars = ScrollBars.Vertical;
            output.BackColor = Color.White;
            output.BorderStyle = BorderStyle.FixedSingle;
            output.Font = new Font("Consolas", 9F);
            output.Location = new Point(22, 158);
            output.Size = new Size(516, 246);

            Controls.Add(title);
            Controls.Add(status);
            Controls.Add(address);
            Controls.Add(bar);
            Controls.Add(openButton);
            Controls.Add(stopButton);
            Controls.Add(restartButton);
            Controls.Add(output);

            Shown += (s, e) => BeginWork();
        }

        private static void Configure(Button button, string text, int x, Size size)
        {
            button.Text = text;
            button.Location = new Point(x, 128);
            button.Size = size;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderColor = Color.FromArgb(203, 213, 225);
            button.BackColor = Color.White;
            button.ForeColor = Color.FromArgb(30, 41, 59);
            button.Cursor = Cursors.Hand;
        }

        private void BeginWork()
        {
            ThreadPool.QueueUserWorkItem(_ =>
            {
                if (!File.Exists(Path.Combine(appRoot, "start-all.ps1")))
                {
                    Fail("找不到 start-all.ps1 —— 这个 EXE 必须放在解压后的工作台目录里。");
                    return;
                }

                Append("正在检查已有服务…");
                if (DetectPorts())
                {
                    Ok("服务已经在运行，直接打开即可。");
                    return;
                }

                Append("正在启动服务（首次运行可能要安装依赖，请稍候）…");
                RunStartScript();
                if (DetectPorts())
                    Ok("启动完成。");
                else
                    Fail("启动没有全部成功，请看下面的日志。");
            });
        }

        private void RunStartScript()
        {
            string ps = FindPowerShell();
            string script = Path.Combine(appRoot, "start-all.ps1");
            var info = new ProcessStartInfo
            {
                FileName = ps,
                Arguments = string.Format(
                    "-NoProfile -ExecutionPolicy Bypass -File \"{0}\" -NoBrowser", script),
                WorkingDirectory = appRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            try { info.StandardOutputEncoding = Encoding.Default; } catch { }
            try { info.StandardErrorEncoding = Encoding.Default; } catch { }

            try
            {
                running = Process.Start(info);
            }
            catch (Exception ex)
            {
                Fail("启动脚本执行失败：" + ex.Message);
                return;
            }
            if (running == null)
            {
                Fail("启动脚本没有跑起来。");
                return;
            }

            running.OutputDataReceived += (s, e) => { if (e.Data != null) Append(e.Data); };
            running.ErrorDataReceived += (s, e) => { if (e.Data != null) Append("! " + e.Data); };
            running.BeginOutputReadLine();
            running.BeginErrorReadLine();
            running.WaitForExit();
            Append("启动脚本执行完毕。");
        }

        private void StopServices()
        {
            ThreadPool.QueueUserWorkItem(_ =>
            {
                Append("正在停止服务…");
                string ps = FindPowerShell();
                string script = Path.Combine(appRoot, "stop-all.ps1");
                if (!File.Exists(script))
                {
                    Fail("找不到 stop-all.ps1。");
                    return;
                }
                var info = new ProcessStartInfo
                {
                    FileName = ps,
                    Arguments = string.Format(
                        "-NoProfile -ExecutionPolicy Bypass -File \"{0}\"", script),
                    WorkingDirectory = appRoot,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                try { info.StandardOutputEncoding = Encoding.Default; } catch { }
                try { info.StandardErrorEncoding = Encoding.Default; } catch { }
                try
                {
                    using (var p = Process.Start(info))
                    {
                        if (p != null)
                        {
                            p.OutputDataReceived += (s, e) => { if (e.Data != null) Append(e.Data); };
                            p.BeginOutputReadLine();
                            p.WaitForExit();
                        }
                    }
                }
                catch (Exception ex)
                {
                    Fail("停止失败：" + ex.Message);
                    return;
                }
                frontendPort = -1;
                backendPort = -1;
                Ok("服务已停止，端口已经释放。");
            });
        }

        private void RestartServices()
        {
            ThreadPool.QueueUserWorkItem(_ =>
            {
                frontendPort = -1;
                backendPort = -1;
                RunStartScript();
                if (DetectPorts())
                    Ok("重启完成。");
                else
                    Fail("重启没有全部成功。");
            });
        }

        /// <summary>Probe the known ports so the EXE knows where the app lives.</summary>
        private bool DetectPorts()
        {
            backendPort = FindPort(BackendPortStart, BackendPortEnd, "/openapi.json", "Cartoon Print Studio API");
            frontendPort = FindPort(FrontendPortStart, FrontendPortEnd, "/", "宜小智");
            if (frontendPort < 0)
                frontendPort = FindPort(FrontendPortStart, FrontendPortEnd, "/", "apple-mobile-web-app-capable");
            if (backendPort < 0 || frontendPort < 0)
                return false;

            string url = "http://127.0.0.1:" + frontendPort + "/";
            SetUi(() =>
            {
                status.Text = "状态：运行中";
                status.ForeColor = Color.FromArgb(22, 163, 74);
                address.Text = "地址：" + url + "    （局域网内其它电脑可用本机 IP + " + frontendPort + " 访问）";
                bar.Style = ProgressBarStyle.Continuous;
                bar.Value = 100;
                openButton.Enabled = true;
                stopButton.Enabled = true;
                restartButton.Enabled = true;
            });
            return true;
        }

        private static int FindPort(int from, int to, string path, string marker)
        {
            for (int port = from; port <= to; port++)
            {
                if (PortAnswers(port, path, marker))
                    return port;
            }
            return -1;
        }

        private static bool PortAnswers(int port, string path, string marker)
        {
            try
            {
                var request = (HttpWebRequest)WebRequest.Create(
                    "http://127.0.0.1:" + port + path);
                request.Timeout = 1500;
                request.ReadWriteTimeout = 1500;
                request.Proxy = null;
                request.UserAgent = "yxz-launcher/1.0";
                using (var response = (HttpWebResponse)request.GetResponse())
                {
                    if ((int)response.StatusCode != 200)
                        return false;
                    using (var stream = response.GetResponseStream())
                    using (var reader = new StreamReader(stream, Encoding.UTF8))
                    {
                        string text = reader.ReadToEnd();
                        return string.IsNullOrEmpty(marker) || text.Contains(marker);
                    }
                }
            }
            catch
            {
                return false;
            }
        }

        private void OpenBrowser()
        {
            if (frontendPort < 0)
            {
                Fail("服务还没起来，先点「重新启动」。");
                return;
            }
            try
            {
                Process.Start(new ProcessStartInfo(
                    "http://127.0.0.1:" + frontendPort + "/") { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                Fail("打不开浏览器：" + ex.Message);
            }
        }

        private static string FindPowerShell()
        {
            string system = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe");
            if (File.Exists(system))
                return system;
            return "powershell.exe";
        }

        private void Append(string line)
        {
            lock (log)
            {
                log.AppendLine(line);
            }
            SetUi(() =>
            {
                lock (log)
                {
                    output.Text = log.ToString();
                    output.SelectionStart = output.Text.Length;
                    output.ScrollToCaret();
                }
            });
        }

        private void Ok(string message)
        {
            Append("[OK] " + message);
        }

        private void Fail(string message)
        {
            Append("[FAIL] " + message);
            SetUi(() =>
            {
                status.Text = "状态：未就绪";
                status.ForeColor = Color.FromArgb(220, 38, 38);
                bar.Style = ProgressBarStyle.Continuous;
                bar.Value = 0;
            });
        }

        private void SetUi(Action action)
        {
            try
            {
                if (IsHandleCreated && !IsDisposed)
                    BeginInvoke(action);
                else
                    action();
            }
            catch
            {
                // The window is closing; nothing to paint any more.
            }
        }
    }
}
