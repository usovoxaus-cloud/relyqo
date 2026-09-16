(()=>{
  const $=id=>document.getElementById(id);
  async function api(url,options={}){const response=await fetch(url,{cache:'no-store',...options});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос');return data}
  async function load(){try{const data=await api('/v1/auth/recovery-email');$('status').textContent=data.verified?`Подтверждённый email: ${data.email}`:'Подтверждённого email пока нет.';$('emailForm').hidden=false;if(data.email)$('email').value=data.email}catch(error){$('status').textContent='';$('error').textContent=error.message==='Войдите в аккаунт'?'Сначала войдите в нужный аккаунт, затем откройте этот раздел.':error.message}}
  $('emailForm').addEventListener('submit',async event=>{event.preventDefault();$('message').textContent='';$('error').textContent='';const button=event.submitter;button.disabled=true;try{const data=await api('/v1/auth/recovery-email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))});$('message').textContent=data.message;$('currentPassword').value=''}catch(error){$('error').textContent=error.message}finally{button.disabled=false}});
  load();
})();
