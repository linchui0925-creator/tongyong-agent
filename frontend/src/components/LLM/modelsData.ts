export type ModelCategory = 'domestic' | 'foreign' | 'open_source' | 'commercial';
export type ModelProvider = string;

export interface ModelInfo {
    id: string;
    name: string;
    displayName: string;
    version: string;
    provider: ModelProvider;
    providerDisplayName: string;
    category: ModelCategory;
    description: string;
    capabilities: string[];
    defaultEndpoint: string;
    docsUrl: string;
    icon: string;
    color: string;
}

export interface ModelGroup {
    category: ModelCategory;
    displayName: string;
    icon: string;
    models: ModelInfo[];
}

export const MODEL_CATEGORIES: Record<ModelCategory, { name: string; icon: string }> = {
    domestic: { name: '国内模型', icon: '🇨🇳' },
    foreign: { name: '国外模型', icon: '🌐' },
    open_source: { name: '开源模型', icon: '📦' },
    commercial: { name: '商业模型', icon: '💎' },
};

export const MODELS_DATA: ModelInfo[] = [
    {
        id: 'qwen-turbo',
        name: 'qwen-turbo',
        displayName: '通义千问 Turbo',
        version: 'v2.5',
        provider: 'tongyi',
        providerDisplayName: '阿里云',
        category: 'domestic',
        description: '阿里云通义千问系列模型，支持中文对话和嵌入',
        capabilities: ['对话', '推理', '代码'],
        defaultEndpoint: 'https://dashscope.aliyuncs.com/api/v1',
        docsUrl: 'https://help.aliyun.com/zh/dashscope/',
        icon: '🐰',
        color: '#FF6A00'
    },
    {
        id: 'qwen-plus',
        name: 'qwen-plus',
        displayName: '通义千问 Plus',
        version: 'v2.5',
        provider: 'tongyi',
        providerDisplayName: '阿里云',
        category: 'domestic',
        description: '阿里云通义千问 Plus，更强推理能力',
        capabilities: ['对话', '推理', '代码', '长文本'],
        defaultEndpoint: 'https://dashscope.aliyuncs.com/api/v1',
        docsUrl: 'https://help.aliyun.com/zh/dashscope/',
        icon: '🐰',
        color: '#FF6A00'
    },
    {
        id: 'qwen-max',
        name: 'qwen-max',
        displayName: '通义千问 Max',
        version: 'v1.0',
        provider: 'tongyi',
        providerDisplayName: '阿里云',
        category: 'domestic',
        description: '阿里云通义千问最强模型，支持超长上下文',
        capabilities: ['对话', '推理', '代码', '长文本', '复杂任务'],
        defaultEndpoint: 'https://dashscope.aliyuncs.com/api/v1',
        docsUrl: 'https://help.aliyun.com/zh/dashscope/',
        icon: '🐰',
        color: '#FF6A00'
    },
    {
        id: 'chatglm-pro',
        name: 'glm-4-pro',
        displayName: 'ChatGLM Pro',
        version: 'v4.0',
        provider: 'zhipu',
        providerDisplayName: '智谱AI',
        category: 'domestic',
        description: '智谱AI最新一代大模型，性能强劲',
        capabilities: ['对话', '推理', '代码', '多模态'],
        defaultEndpoint: 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
        docsUrl: 'https://open.bigmodel.cn/',
        icon: '🔵',
        color: '#4A90E2'
    },
    {
        id: 'chatglm-plus',
        name: 'glm-4-plus',
        displayName: 'ChatGLM Plus',
        version: 'v4.0',
        provider: 'zhipu',
        providerDisplayName: '智谱AI',
        category: 'domestic',
        description: '智谱AI增强版模型，性价比高',
        capabilities: ['对话', '推理', '代码'],
        defaultEndpoint: 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
        docsUrl: 'https://open.bigmodel.cn/',
        icon: '🔵',
        color: '#4A90E2'
    },
    {
        id: 'baichuan4',
        name: 'Baichuan4',
        displayName: '百川4',
        version: 'v4.0',
        provider: 'baichuan',
        providerDisplayName: '百川智能',
        category: 'domestic',
        description: '百川智能大模型，中文能力突出',
        capabilities: ['对话', '推理', '创作'],
        defaultEndpoint: 'https://api.baichuan-ai.com/v1/chat/completions',
        docsUrl: 'https://www.baichuan-ai.com/',
        icon: '🌊',
        color: '#00D4AA'
    },
    {
        id: 'wenxin4',
        name: 'ernie-4.0',
        displayName: '文心一言4.0',
        version: 'v4.0',
        provider: 'wenxin',
        providerDisplayName: '百度文心',
        category: 'domestic',
        description: '百度文心大模型，知识增强',
        capabilities: ['对话', '推理', '知识问答', '创作'],
        defaultEndpoint: 'https://qianfan.baidubce.com/v2/chat/completions',
        docsUrl: 'https://cloud.baidu.com/product/wenxin.html',
        icon: '🟢',
        color: '#3300FF'
    },
    {
        id: 'spark4',
        name: 'spark-v4.0',
        displayName: '讯飞星火4.0',
        version: 'v4.0',
        provider: 'xfyun',
        providerDisplayName: '讯飞星火',
        category: 'domestic',
        description: '科大讯飞星火大模型，语音交互强',
        capabilities: ['对话', '语音', '多模态'],
        defaultEndpoint: 'https://spark-api.xf-yun.com/v4.0/chat',
        docsUrl: 'https://xinghuo.xfyun.cn/',
        icon: '🔴',
        color: '#FF4444'
    },
    {
        id: 'claude-3-5-sonnet',
        name: 'claude-3-5-sonnet-20240620',
        displayName: 'Claude 3.5 Sonnet',
        version: 'v3.5',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'foreign',
        description: 'Anthropic最强模型，擅长推理和编程',
        capabilities: ['对话', '推理', '代码', '分析'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'claude-sonnet-4-20250514',
        name: 'claude-sonnet-4-20250514',
        displayName: 'Claude Sonnet 4',
        version: 'v4.0',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'foreign',
        description: 'Anthropic最新 Sonnet 模型，最强编程能力，200K 上下文',
        capabilities: ['对话', '推理', '代码', '分析', '长上下文'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'claude-opus-4-20250514',
        name: 'claude-opus-4-20250514',
        displayName: 'Claude Opus 4',
        version: 'v4.0',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'foreign',
        description: 'Anthropic最新旗舰模型，最强通用推理能力，200K 上下文',
        capabilities: ['对话', '推理', '代码', '分析', '复杂任务', '长上下文'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'claude-3-7-sonnet',
        name: 'claude-3-7-sonnet-20250514',
        displayName: 'Claude 3.7 Sonnet',
        version: 'v3.7',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'foreign',
        description: 'Anthropic 3.7版本模型，更强推理和编程能力，支持200K上下文',
        capabilities: ['对话', '推理', '代码', '分析', '长上下文'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'claude-3-7-opus',
        name: 'claude-3-7-opus-20250514',
        displayName: 'Claude 3.7 Opus',
        version: 'v3.7',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'foreign',
        description: 'Anthropic 3.7 旗舰模型，最强推理能力，支持200K上下文',
        capabilities: ['对话', '推理', '代码', '分析', '复杂任务', '长上下文'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'claude-3-5-haiku',
        name: 'claude-3-5-haiku-20241022',
        displayName: 'Claude 3.5 Haiku',
        version: 'v3.5',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'commercial',
        description: 'Anthropic极速轻量模型，快速响应，性价比高',
        capabilities: ['对话', '快速响应'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'claude-3-opus',
        name: 'claude-3-opus-20240229',
        displayName: 'Claude 3 Opus',
        version: 'v3.0',
        provider: 'anthropic',
        providerDisplayName: 'Anthropic',
        category: 'foreign',
        description: 'Anthropic旗舰模型，最强推理能力',
        capabilities: ['对话', '推理', '代码', '分析', '复杂任务'],
        defaultEndpoint: 'https://api.anthropic.com/v1',
        docsUrl: 'https://docs.anthropic.com/',
        icon: '🤖',
        color: '#CC785C'
    },
    {
        id: 'gpt-4o',
        name: 'gpt-4o',
        displayName: 'GPT-4o',
        version: 'v4.0',
        provider: 'openai',
        providerDisplayName: 'OpenAI',
        category: 'foreign',
        description: 'OpenAI最新多模态模型，原生支持语音',
        capabilities: ['对话', '推理', '代码', '视觉', '语音'],
        defaultEndpoint: 'https://api.openai.com/v1',
        docsUrl: 'https://platform.openai.com/',
        icon: '💬',
        color: '#10A37F'
    },
    {
        id: 'gpt-4-turbo',
        name: 'gpt-4-turbo',
        displayName: 'GPT-4 Turbo',
        version: 'v2024-04',
        provider: 'openai',
        providerDisplayName: 'OpenAI',
        category: 'foreign',
        description: 'OpenAI高性能模型，上下文更长',
        capabilities: ['对话', '推理', '代码', '长文本'],
        defaultEndpoint: 'https://api.openai.com/v1',
        docsUrl: 'https://platform.openai.com/',
        icon: '💬',
        color: '#10A37F'
    },
    {
        id: 'gpt-3.5-turbo',
        name: 'gpt-3.5-turbo',
        displayName: 'GPT-3.5 Turbo',
        version: 'v2024-02',
        provider: 'openai',
        providerDisplayName: 'OpenAI',
        category: 'commercial',
        description: 'OpenAI经济实惠的快速模型',
        capabilities: ['对话', '快速响应'],
        defaultEndpoint: 'https://api.openai.com/v1',
        docsUrl: 'https://platform.openai.com/',
        icon: '💬',
        color: '#10A37F'
    },
    {
        id: 'gemini-1.5-pro',
        name: 'gemini-1.5-pro',
        displayName: 'Gemini 1.5 Pro',
        version: 'v1.5',
        provider: 'google',
        providerDisplayName: 'Google',
        category: 'foreign',
        description: 'Google多模态模型，超长上下文',
        capabilities: ['对话', '推理', '多模态', '长文本'],
        defaultEndpoint: 'https://generativelanguage.googleapis.com/v1beta/models',
        docsUrl: 'https://ai.google.dev/',
        icon: '🔷',
        color: '#4285F4'
    },
    {
        id: 'gemini-1.5-flash',
        name: 'gemini-1.5-flash',
        displayName: 'Gemini 1.5 Flash',
        version: 'v1.5',
        provider: 'google',
        providerDisplayName: 'Google',
        category: 'foreign',
        description: 'Google快速响应模型',
        capabilities: ['对话', '快速响应', '多模态'],
        defaultEndpoint: 'https://generativelanguage.googleapis.com/v1beta/models',
        docsUrl: 'https://ai.google.dev/',
        icon: '🔷',
        color: '#4285F4'
    },
    {
        id: 'llama-3.1-70b',
        name: 'llama-3.1-70b-instruct',
        displayName: 'Llama 3.1 70B',
        version: 'v3.1',
        provider: 'ollama',
        providerDisplayName: 'Meta/Mozilla',
        category: 'open_source',
        description: 'Meta开源最强模型，支持本地部署',
        capabilities: ['对话', '推理', '代码'],
        defaultEndpoint: 'http://localhost:11434/api/chat',
        docsUrl: 'https://ollama.com/',
        icon: '🦙',
        color: '#FF9A00'
    },
    {
        id: 'llama-3.1-8b',
        name: 'llama-3.1-8b-instruct',
        displayName: 'Llama 3.1 8B',
        version: 'v3.1',
        provider: 'ollama',
        providerDisplayName: 'Meta/Mozilla',
        category: 'open_source',
        description: 'Meta开源轻量模型，适合本地部署',
        capabilities: ['对话', '快速响应'],
        defaultEndpoint: 'http://localhost:11434/api/chat',
        docsUrl: 'https://ollama.com/',
        icon: '🦙',
        color: '#FF9A00'
    },
    {
        id: 'qwen2.5-72b',
        name: 'qwen2.5-72b-instruct',
        displayName: 'Qwen2.5 72B',
        version: 'v2.5',
        provider: 'ollama',
        providerDisplayName: '阿里云开源',
        category: 'open_source',
        description: '阿里云开源最强模型，中文优化',
        capabilities: ['对话', '推理', '代码', '中文'],
        defaultEndpoint: 'http://localhost:11434/api/chat',
        docsUrl: 'https://ollama.com/',
        icon: '🐰',
        color: '#FF6A00'
    },
    {
        id: 'deepseek-v2.5',
        name: 'deepseek-v2.5',
        displayName: 'DeepSeek V2.5',
        version: 'v2.5',
        provider: 'deepseek',
        providerDisplayName: 'DeepSeek',
        category: 'domestic',
        description: '深度求索大模型，性价比极高',
        capabilities: ['对话', '推理', '代码', '数学'],
        defaultEndpoint: 'https://api.deepseek.com/v1/chat/completions',
        docsUrl: 'https://platform.deepseek.com/',
        icon: '🔻',
        color: '#0066FF'
    },
    {
        id: 'yi-large',
        name: 'yi-large',
        displayName: 'Yi Large',
        version: 'v1.5',
        provider: 'yi',
        providerDisplayName: '零一万物',
        category: 'domestic',
        description: '零一万物大模型，长上下文',
        capabilities: ['对话', '推理', '长文本'],
        defaultEndpoint: 'https://api.lingyiwanwu.com/v1/chat/completions',
        docsUrl: 'https://platform.lingyiwanwu.com/',
        icon: '🌟',
        color: '#FFD700'
    }
];

export function getModelsByCategory(): ModelGroup[] {
    const groups: Record<ModelCategory, ModelInfo[]> = {
        domestic: [],
        foreign: [],
        open_source: [],
        commercial: []
    };

    MODELS_DATA.forEach(model => {
        groups[model.category].push(model);
    });

    return Object.entries(MODEL_CATEGORIES).map(([category, info]) => ({
        category: category as ModelCategory,
        displayName: info.name,
        icon: info.icon,
        models: groups[category as ModelCategory]
    })).filter(group => group.models.length > 0);
}

export function searchModels(query: string): ModelInfo[] {
    const lowerQuery = query.toLowerCase();
    return MODELS_DATA.filter(model =>
        model.displayName.toLowerCase().includes(lowerQuery) ||
        model.name.toLowerCase().includes(lowerQuery) ||
        model.providerDisplayName.toLowerCase().includes(lowerQuery) ||
        model.description.toLowerCase().includes(lowerQuery) ||
        model.capabilities.some(c => c.toLowerCase().includes(lowerQuery))
    );
}

export function getModelById(id: string): ModelInfo | undefined {
    return MODELS_DATA.find(m => m.id === id);
}

export function getDefaultModel(): ModelInfo {
    return MODELS_DATA[0];
}
