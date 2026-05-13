function loadContent() {
    let userLang = 'en';
    const browserLanguage = navigator.language || navigator.userLanguage;
    console.log('userLang', userLang, 'browserLanguage', browserLanguage)

    if (browserLanguage.includes('ru')) {
        userLang = 'ru';
    } else if (browserLanguage.includes('en')) {
        userLang = 'en';
    } else if (browserLanguage.includes('pl')) {
        userLang = 'pl';
    } else if (browserLanguage.includes('uk')) {
        userLang = 'uk';
    } else if (browserLanguage.includes('ka')) {
        userLang = 'ka';
    } else if (browserLanguage.includes('hy')) {
        userLang = 'hy';
    } else if (browserLanguage.includes('es')) {
        userLang = 'es';
    }


    console.log('userLang 2', userLang, browserLanguage.includes('ru'))
    fetch(`https://autohelperbot.com/${userLang}/profile/header`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok ' + response.statusText);
            }
            return response.text(); // Получаем текстовый ответ
        })
        .then(data => {
            document.getElementById('autohelperbot_dannie').innerHTML = data;
            var links = document.querySelectorAll('a');

            links.forEach(function(link) {
                link.setAttribute('target', '_blank');
            });
        })
        .catch(error => {
            console.error('Ошибка при выполнении запроса:', error);
        });
}

// Загружаем контент при загрузке страницы
window.onload = loadContent;