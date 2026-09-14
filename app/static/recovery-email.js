(()=>{
  const form=document.getElementById('recoveryEmailForm');
  const status=document.getElementById('recoveryEmailStatus');
  async function load(){
    try{const response=await fetch('/v1/auth/recovery-email',{cache:'no-store'});if(!response.ok)return;const data=await response.json();status.textContent=data.verified?'Подтверждённый email: '+data.email:'Email ещё не подтверждён. Добавьте его, чтобы восстановить аккаунт при потере пароля.';}
    catch{status.textContent='Не удалось проверить email. Обновите страницу при восстановлении соединения.';}
  }
  const dashboard=document.getElementById('dashboard');
  new MutationObserver(()=>{if(!dashboard.classList.contains('hidden'))load();}).observe(dashboard,{attributes:true,attributeFilter:['class']});
  if(!dashboard.classList.contains('hidden'))load();
  form.addEventListener('submit',async event=>{
    event.preventDefault();const button=form.querySelector('button');const error=document.getElementById('recoveryEmailError');error.textContent='';error.classList.add('hidden');button.disabled=true;
    try{const response=await fetch('/v1/auth/recovery-email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(form))),cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Проверьте email и пароль.');status.textContent=data.message;form.reset();}
    catch(e){error.classList.remove('hidden');error.textContent=e instanceof TypeError?'Нет соединения. Попробуйте снова.':e.message;}
    finally{form.elements.current_password.value='';button.disabled=false;}
  });
})();
