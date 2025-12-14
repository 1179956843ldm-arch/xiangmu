from fastapi import FastAPI, Form

app = FastAPI()

@app.post("/login")
async def login(
        username: str = Form(...),
        password: str = Form(...)
):
    # 在后台打印用户名和密码
    print(f"用户名：{username}")
    print(f"密码：{password}")

    # 返回一个简单的响应给前端
    return {"message": "OK SUCCESS", "username": username}