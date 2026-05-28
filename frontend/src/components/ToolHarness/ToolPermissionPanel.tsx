// 工具权限管理面板组件
import React, { useState, useEffect } from 'react';

interface Tool {
  id: string;
  name: string;
  description: string;
  category: string;
  permission_level: number;
  enabled: boolean;
  requires_approval: boolean;
}

interface Permission {
  tool_id: string;
  tool_name: string;
  granted: boolean;
}

export const ToolPermissionPanel: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [selectedRole, setSelectedRole] = useState<string>('user');
  const [permissions, setPermissions] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetchTools();
    fetchPermissions();
  }, [selectedRole]);

  const fetchTools = async () => {
    try {
      const response = await fetch('/api/tools');
      const data = await response.json();
      setTools(data);
    } catch (error) {
      console.error('获取工具列表失败:', error);
    }
  };

  const fetchPermissions = async () => {
    try {
      const response = await fetch(`/api/tools/permissions/${selectedRole}`);
      const data = await response.json();
      const permMap: Record<string, boolean> = {};
      data.forEach((p: Permission) => {
        permMap[p.tool_name] = p.granted;
      });
      setPermissions(permMap);
    } catch (error) {
      console.error('获取权限列表失败:', error);
    }
  };

  const togglePermission = async (toolName: string, granted: boolean) => {
    try {
      await fetch(`/api/tools/permissions/${selectedRole}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: toolName, granted })
      });
      setPermissions(prev => ({ ...prev, [toolName]: granted }));
    } catch (error) {
      console.error('更新权限失败:', error);
    }
  };

  const roles = ['owner', 'admin', 'user', 'guest'];

  return (
    <div className="tool-permission-panel">
      <div className="panel-header">
        <h2>🔒 工具权限管理</h2>
        <select 
          value={selectedRole} 
          onChange={(e) => setSelectedRole(e.target.value)}
          className="role-selector"
        >
          {roles.map(role => (
            <option key={role} value={role}>{role.toUpperCase()}</option>
          ))}
        </select>
      </div>

      <div className="tools-list">
        {tools.map(tool => (
          <div key={tool.id} className="tool-permission-item">
            <div className="tool-info">
              <div className="tool-name">{tool.name}</div>
              <div className="tool-category">{tool.category}</div>
            </div>
            <div className="tool-permission">
              <label className="switch">
                <input
                  type="checkbox"
                  checked={permissions[tool.name] || false}
                  onChange={(e) => togglePermission(tool.name, e.target.checked)}
                />
                <span className="slider"></span>
              </label>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ToolPermissionPanel;
