/**
 * DesktopBridge 前端服务
 *
 * 前端作为 WebSocket 代理：
 * 1. 建立 WebSocket 连接到后端 /ws/desktop/{session_id}
 * 2. 接收后端发来的 desktop_cmd 命令
 * 3. 在用户本机执行（AppleScript / 系统命令 / CDP）
 * 4. 将结果返回给后端
 */

export interface DesktopCommand {
  cmd_id: string;
  action: 'osascript' | 'bash' | 'cliclick' | 'browser_cdp' | 'screencapture';
  script?: string;       // osascript 时用
  command?: string;      // bash 时用
  args?: string[];       // cliclick 时用
  cdp_url?: string;      // browser_cdp 时用
  browser_action?: string;
  browser_params?: Record<string, any>;
  path?: string;         // screencapture 路径
}

export interface DesktopResult {
  cmd_id: string;
  status: 'success' | 'error';
  result?: string;
  error?: string;
}

type MessageHandler = (cmd: DesktopCommand) => void;

class DesktopBridgeService {
  private ws: WebSocket | null = null;
  private sessionId: string = '';
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingCommands = new Map<string, {
    resolve: (result: DesktopResult) => void;
    reject: (error: Error) => void;
    timeout: ReturnType<typeof setTimeout>;
  }>();
  private handlers: Set<MessageHandler> = new Set();
  private isConnected = false;

  /**
   * 连接后端 DesktopBridge WebSocket
   */
  connect(sessionId: string): Promise<void> {
    this.sessionId = sessionId;

    return new Promise((resolve, reject) => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/desktop/${sessionId}`;

      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log('[DesktopBridge] WebSocket 已连接');
          this.isConnected = true;
          this.clearReconnectTimer();
          resolve();
        };

        this.ws.onmessage = async (event) => {
          try {
            const data = JSON.parse(event.data);
            await this.handleMessage(data);
          } catch (e) {
            console.error('[DesktopBridge] 消息解析失败:', e);
          }
        };

        this.ws.onerror = (error) => {
          console.error('[DesktopBridge] WebSocket 错误:', error);
          this.isConnected = false;
        };

        this.ws.onclose = () => {
          console.log('[DesktopBridge] WebSocket 断开');
          this.isConnected = false;
          this.scheduleReconnect();
        };
      } catch (err) {
        reject(err);
      }
    });
  }

  /**
   * 处理从后端收到的消息
   */
  private async handleMessage(data: any): Promise<void> {
    if (data.type === 'desktop_cmd') {
      const cmd: DesktopCommand = data as DesktopCommand;
      console.log('[DesktopBridge] 收到命令:', cmd);

      // 先检查是否有待处理的 pending 命令
      const pending = this.pendingCommands.get(cmd.cmd_id);

      try {
        const result = await this.executeCommand(cmd);

        if (pending) {
          pending.resolve({ cmd_id: cmd.cmd_id, status: 'success', result });
          this.pendingCommands.delete(cmd.cmd_id);
          clearTimeout(pending.timeout);
        } else {
          // 没有 pending，通过 WebSocket 发送结果
          await this.sendResult({ cmd_id: cmd.cmd_id, status: 'success', result });
        }
      } catch (err: any) {
        const errorMsg = err?.message || String(err);
        console.error('[DesktopBridge] 命令执行失败:', errorMsg);

        if (pending) {
          pending.resolve({ cmd_id: cmd.cmd_id, status: 'error', error: errorMsg });
          this.pendingCommands.delete(cmd.cmd_id);
          clearTimeout(pending.timeout);
        } else {
          await this.sendResult({ cmd_id: cmd.cmd_id, status: 'error', error: errorMsg });
        }
      }
    } else if (data.type === 'ping') {
      this.ws?.send(JSON.stringify({ type: 'pong', time: data.time }));
    }
  }

  /**
   * 执行 desktop 命令
   */
  private async executeCommand(cmd: DesktopCommand): Promise<string> {
    switch (cmd.action) {
      case 'osascript':
        return this.executeOsascript(cmd.script!);

      case 'bash':
        return this.executeBash(cmd.command!);

      case 'cliclick':
        return this.executeCliclick(cmd.args || []);

      case 'browser_cdp':
        return this.executeBrowserCDP(cmd);

      case 'screencapture':
        return this.executeScreencapture(cmd.path!);

      default:
        throw new Error(`未知命令类型: ${cmd.action}`);
    }
  }

  /**
   * 执行 AppleScript
   */
  private executeOsascript(_script: string): Promise<string> {
    return new Promise((_resolve, reject) => {
      reject(new Error('osascript 需要本地代理程序，请安装 DesktopBridge agent'));
    });
  }

  /**
   * 执行 bash 命令
   */
  private executeBash(_command: string): Promise<string> {
    return new Promise((_resolve, reject) => {
      reject(new Error('bash 需要本地代理程序，请安装 DesktopBridge agent'));
    });
  }

  /**
   * 执行 cliclick（鼠标控制）
   */
  private executeCliclick(_args: string[]): Promise<string> {
    return new Promise((_resolve, reject) => {
      reject(new Error('cliclick 需要本地代理程序，请安装 DesktopBridge agent'));
    });
  }

  /**
   * 通过 CDP 控制浏览器
   */
  private async executeBrowserCDP(cmd: DesktopCommand): Promise<string> {
    const { cdp_url, browser_action, browser_params } = cmd;

    if (!cdp_url) {
      throw new Error('browser_cdp 需要 cdp_url');
    }

    try {
      const response = await fetch(cdp_url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: Date.now(),
          method: this.mapBrowserAction(browser_action || ''),
          params: browser_params,
        }),
      });

      const result = await response.json();
      return JSON.stringify(result);
    } catch (err: any) {
      throw new Error(`CDP 执行失败: ${err.message}`);
    }
  }

  /**
   * 映射 browser_action 到 CDP method
   */
  private mapBrowserAction(action: string): string {
    const map: Record<string, string> = {
      'navigate': 'Page.navigate',
      'click': 'Input.dispatchMouseEvent',
      'type': 'Input.dispatchKeyEvent',
      'screenshot': 'Page.captureScreenshot',
      'get_text': 'Runtime.evaluate',
      'scroll': 'Input.dispatchMouseEvent',
    };
    return map[action] || action;
  }

  /**
   * 执行截图
   */
  private executeScreencapture(_path: string): Promise<string> {
    return new Promise((_resolve, reject) => {
      reject(new Error('screencapture 需要本地代理程序，请安装 DesktopBridge agent'));
    });
  }

  /**
   * 发送执行结果到后端
   */
  private async sendResult(result: DesktopResult): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'desktop_result', ...result }));
    }
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    this.clearReconnectTimer();
    this.pendingCommands.forEach((p) => {
      clearTimeout(p.timeout);
      p.reject(new Error('连接已断开'));
    });
    this.pendingCommands.clear();
    this.ws?.close();
    this.ws = null;
    this.isConnected = false;
  }

  /**
   * 注册命令处理器（用于主动推送模式）
   */
  onCommand(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      if (!this.isConnected && this.sessionId) {
        console.log('[DesktopBridge] 尝试重连...');
        this.connect(this.sessionId).catch(() => {});
      }
    }, 5000);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  get connected(): boolean {
    return this.isConnected;
  }
}

// 单例导出
export const desktopBridge = new DesktopBridgeService();