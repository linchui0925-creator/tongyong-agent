"""
第三方API代理接口，解决前端跨域问题
"""
from fastapi import APIRouter, Request, HTTPException
import httpx
from typing import Dict, Any

router = APIRouter(prefix="/api/proxy", tags=["proxy"])

# 允许代理的域名白名单，避免被滥用
ALLOWED_DOMAINS = {
    "api.edgefn.net",
    "ark.cn-beijing.volces.com",
    "api.deepseek.com",
    "api.openai.com",
    "dashscope.aliyuncs.com",
    "aip.baidubce.com",
    "api.minimax.chat",
    "api.moonshot.cn",
    "api.siliconflow.cn"
}

@router.post("")
async def proxy_request(request: Request):
    try:
        data = await request.json()
        base_url = data.get("base_url")
        path = data.get("path", "")
        method = data.get("method", "POST").upper()
        headers = data.get("headers", {})
        body = data.get("body", {})

        if not base_url:
            raise HTTPException(status_code=400, detail="base_url 不能为空")

        # 校验域名在白名单内
        from urllib.parse import urlparse
        parsed_url = urlparse(base_url)
        if parsed_url.netloc not in ALLOWED_DOMAINS:
            raise HTTPException(status_code=403, detail=f"域名 {parsed_url.netloc} 不在允许代理的白名单内")

        # 拼接完整URL
        if not base_url.endswith("/"):
            base_url += "/"
        if path.startswith("/"):
            path = path.lstrip("/")
        full_url = base_url + path

        # 过滤敏感header
        filtered_headers = {
            k: v for k, v in headers.items() 
            if k.lower() not in ["host", "content-length", "connection"]
        }

        # 转发请求
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            request_args = {
                "method": method,
                "url": full_url,
                "headers": filtered_headers,
            }
            if method in ["POST", "PUT", "PATCH"]:
                request_args["json"] = body
            else:
                request_args["params"] = body

            response = await client.request(**request_args)
            response.raise_for_status()
            
            # 根据返回内容类型返回
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            else:
                return response.text

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"代理请求失败: {str(e)}")
