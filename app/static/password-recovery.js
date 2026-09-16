/* Keep the secret in this closure only: no URL query, storage, analytics or third-party scripts. */
(()=>{
  const $=id=>document.getElementById(id);
  let token='';
  const mode=location.pathname==='/reset-password'?'reset':location.pathname==='/verify-email'?'verify':'forgot';
  function initialize(){
    token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
    history.replaceState(null,'',location.pathname);
    $('message').textContent='';$('error').textContent='';$('retry').hidden=true;
    $('forgotForm').hidden=mode!=='forgot';$('resetForm').hidden=mode!=='reset';$('verifyForm').hidden=mode!=='verify';$('legacyHelp').hidden=mode!=='forgot';$('openReset').hidden=mode!=='forgot';
    const legacyReset=mode==='reset'&&Boolean(token);
    $('codeFields').hidden=legacyReset;
    for(const id of ['resetEmail','resetCode']){$(id).disabled=legacyReset;$(id).required=!legacyReset;}
    if(mode!=='forgot'){
      $('title').textContent=mode==='reset'?'Новый пароль':'Подтвердите email';
      $('intro').textContent=mode==='reset'?(legacyReset?'Установите новый пароль по ссылке из письма.':'Введите email, код из письма и новый пароль. Код действует 10 минут; доступно 5 попыток.'):'Подтвердите адрес для восстановления доступа к вашему аккаунту.';
      if(mode==='verify'&&!token){$('error').textContent='Ссылка отсутствует или уже использована в этом окне. Откройте ссылку из письма заново.';$('verifyForm').hidden=true;$('retry').hidden=false;}
    }
  }
  initialize();
  window.addEventListener('hashchange',initialize);
  for(const kind of ['forgot','reset','verify'])$(kind+'Form').addEventListener('submit',async event=>{
    event.preventDefault();$('error').textContent='';$('message').textContent='';
    const form=event.currentTarget,button=form.querySelector('button');
    if(kind==='reset'&&$('newPassword').value!==$('confirmPassword').value){$('error').textContent='Пароли не совпадают.';return;}
    button.disabled=true;
    const body=kind==='forgot'?{email:$('email').value.trim()}:kind==='reset'?{...(token?{token}:{email:$('resetEmail').value.trim(),code:$('resetCode').value.trim()}),new_password:$('newPassword').value,confirm_password:$('confirmPassword').value}:{token};
    try{
      const endpoint=kind==='forgot'?'forgot-password':kind==='reset'?'reset-password':'verify-email';
      const response=await fetch('/v1/auth/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
      const data=await response.json();
      if(!response.ok){if(response.status===400&&kind!=='forgot')$('retry').hidden=false;throw new Error(typeof data.detail==='string'?data.detail:'Проверьте введённые данные.');}
      $('message').textContent=data.message;
      if(kind==='forgot'){$('openReset').textContent='Ввести полученный код →'}
      else{form.reset();token='';form.hidden=true;}
    }catch(error){$('error').textContent=error instanceof TypeError?'Нет соединения. Проверьте сеть и попробуйте снова.':error.message;}
    finally{button.disabled=false;}
  });
})();
