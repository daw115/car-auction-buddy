let userLang = 'en';
const browserLanguage = navigator.language || navigator.userLanguage;

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

function onDataCatalog(data) {

    var elements = (data.response);

    elements.forEach(function(lot) {

        // copart
        if($('table#serverSideDataTable a.search-results').length > 0) {

            $('table#serverSideDataTable a.search-results:contains('+lot['lot_id']+')').parent().parent().prev().append(lot['who_sell']);

            if(lot['seller_reserve_text'] != undefined && lot['seller_reserve_text'] != '') {
                $('table#serverSideDataTable a.search-results:contains('+lot['lot_id']+')').parent().parent().prev().append( lot['seller_reserve'] );
            }
            else if(lot['seller_reserve'] == '1') {
                $('table#serverSideDataTable a.search-results:contains('+lot['lot_id']+')').parent().parent().prev().append('<a onclick="window.open(\'tg://resolve?domain=autohelperbot_com_bot&start=lot_' + lot['lot_id'] + '\')" href="javascript:void(0);" style="margin: 0 0 5px 0;white-space: nowrap;color: #fff;display: inline-block;font-weight: 400;background-color: #fd6921 !important;border: 1px solid #fd6921 !important;padding: 1px 3px;font-size: 12px;" title="' + (userLang=='ru' ? 'Открыть в Telegram' : 'Open in Telegram') + '">' + (userLang=='ru' ? 'Сумма резерва' : 'Reserve price') + '</a>');
            }

        }


        if($('div.datatable-results span.search_result_lot_number').length > 0) {

            $('div.datatable-results span.search_result_lot_number:contains('+lot['lot_id']+')').parent().parent().append(lot['who_sell']);

            if(lot['seller_reserve_text'] != undefined && lot['seller_reserve_text'] != '') {
                $('div.datatable-results span.search_result_lot_number:contains('+lot['lot_id']+')').parent().parent().append( lot['seller_reserve'] );
            }
            else if(lot['seller_reserve'] == '1') {
                $('div.datatable-results span.search_result_lot_number:contains('+lot['lot_id']+')').parent().parent().append('<a onclick="window.open(\'tg://resolve?domain=autohelperbot_com_bot&start=lot_' + lot['lot_id'] + '\')" href="javascript:void(0);" style="margin: 0 0 5px 0;white-space: nowrap;color: #fff;display: inline-block;font-weight: 400;background-color: #fd6921 !important;border: 1px solid #fd6921 !important;padding: 1px 3px;font-size: 12px;" title="' + (userLang=='ru' ? 'Открыть в Telegram' : 'Open in Telegram') + '">' + (userLang=='ru' ? 'Сумма резерва' : 'Reserve price') + '</a>');
            }

        }


        // iaai
        if($('#ListingGrid .table-body .table-row').length > 0) {

            $('#btnShowWatch' + lot['item_id']).parent().parent().find('.table-cell--inner .table-cell:nth-child(1)').prepend(lot['who_sell']);

            $('#btnShowWatch' + lot['item_id']).parent().parent().find('.table-cell--inner .table-cell:nth-child(3) .data-list__item:last').remove();
            $('#btnShowWatch' + lot['item_id']).parent().parent().find('.table-cell--inner .table-cell:nth-child(3)').append('<li class="data-list__item"><span class="data-list__label">VIN:</span><span class="" title="Please log in as a buyer">'+ lot['vin_code'] +'</span></li>');

            if(lot['seller_reserve'] != '') {
                $(lot['seller_reserve']).prependTo($('#btnShowWatch' + lot['item_id']).parent().parent().find('.table-cell--inner .table-cell:last'));
            }
        }


        if($('div.table.table--image-view').length > 0) {
            $('#' + lot['item_id']).parent().append(lot['who_sell']);
            $('#' + lot['item_id']).parent().parent().find('.row:first div:nth-child(2) .data-list__item:last .data-list__value').html(lot['vin_code']);

            if(lot['seller_reserve'] != '') {
                $(lot['seller_reserve']).prependTo($('#' + lot['item_id']).parent().parent().parent().find('.table-cell.table-cell--actions'));
            }
        }

        if($('div.table.table-mobile').length > 0) {
            $('.PrebidStatusText-' + lot['lot_id']).parents('.table-row-main').find('.table-cell--vehicle-name').append(lot['who_sell']);
        }

        if($('table.table.table--table-view').length > 0) {
            $('#' + lot['item_id']).append(lot['who_sell']);
            $('#' + lot['item_id']).parent().next().find('span').html(lot['vin_code']);

            if(lot['seller_reserve'] != '') {
                $(lot['seller_reserve']).appendTo($('#' + lot['item_id']).parent().next().find('span'));
            }
        }


        var hasLoginLinks = elements.some(function(lot) {
            return lot['who_sell'] && lot['who_sell'].includes('autohelperbot.com/en/login') ||
                lot['who_sell'] && lot['who_sell'].includes('autohelperbot.com/ru/login') ||
                lot['who_sell'] && lot['who_sell'].includes('/login');
        });
        if(hasLoginLinks) {
            if($('.table-cell--inner.table-row-inner-col-checkbox').length > 0) {
                console.log('Found .table-cell--inner.table-row-inner-col-checkbox elements:', $('.table-cell--inner.table-row-inner-col-checkbox').length);

                var targetElement = null;

                targetElement = $('.table-cell--inner.table-row-inner-col-checkbox').filter(function() {
                    var lotNumber = $(this).find('.data-list__item:first .data-list__value').text().trim();
                    return parseInt(lotNumber) == lot['lot_id'];
                });

                if(targetElement.length === 0) {
                    targetElement = $('.table-cell--inner.table-row-inner-col-checkbox').filter(function() {
                        var lotNumber = $(this).find('.data-list__item:first .data-list__value').text().trim();
                        return parseInt(lotNumber) == lot['item_id'];
                    });
                }


                if(targetElement.length > 0) {
                    var parentRow = targetElement.closest('.table-cell--data');
                    if(parentRow.length > 0) {
                        parentRow.prepend(lot['who_sell']);
                    } else {
                        targetElement.prepend(lot['who_sell']);
                    }

                    if(lot['vin_code']) {
                        var vinElement = targetElement.closest('.table-row').find('.data-list__item').filter(function() {
                            return $(this).find('.data-list__label').text().toLowerCase().includes('vin');
                        });
                        if(vinElement.length > 0) {
                            vinElement.find('.data-list__value').html(lot['vin_code']);
                        }
                    }

                    if(lot['seller_reserve'] != '') {
                        var reserveTarget = targetElement.closest('.table-row').find('.table-cell--data:last');
                        if(reserveTarget.length === 0) {
                            reserveTarget = targetElement.parent();
                        }
                        $(lot['seller_reserve']).prependTo(reserveTarget);
                    }
                } else {
                    $('.table-cell--inner.table-row-inner-col-checkbox').each(function(index) {
                        var lotNumber = $(this).find('.data-list__item:first .data-list__value').text().trim();
                    });
                }
            }
        }

    });

}



var timer = setInterval(function() {

    if (window.jQuery){

        if($('table#serverSideDataTable a.search-results').length > 0) {
            if($('table#serverSideDataTable a.search-results').hasClass('autohelperbot') == false) {

                if($('table#serverSideDataTable a.search-results').length > 0) {

                    $('table#serverSideDataTable a.search-results').addClass('autohelperbot');

                    var lot_ids = $.makeArray($('table#serverSideDataTable a.search-results')).map(x => ($(x).text()));

                    var found_lots = {
                        lots: JSON.stringify(lot_ids)
                    }

                    chrome.runtime.sendMessage({
                        found_lots: found_lots,
                        userLang: userLang,
                        action: 'postLots',
                        url: `https://autohelperbot.com/copart_lots?autohelperbot_app=1.0&json=${true}`
                    }, function(response) {
                        if (chrome.runtime.lastError) {
                            console.error('Error:', chrome.runtime.lastError.message);
                            return;
                        }
                        onDataCatalog(response.data);
                    });


                }

            }
        }


        if($('div.datatable-results span.search_result_lot_number').length > 0) {
            if($('div.datatable-results span.search_result_lot_number').hasClass('autohelperbot') == false) {

                if($('div.datatable-results span.search_result_lot_number').length > 0) {

                    $('div.datatable-results span.search_result_lot_number').addClass('autohelperbot');

                    var lot_ids = $.makeArray($('div.datatable-results span.search_result_lot_number')).map(x => ($(x).text().trim()));

                    var found_lots = {
                        lots: JSON.stringify(lot_ids)
                    }

                    chrome.runtime.sendMessage({
                        found_lots: found_lots,
                        userLang: userLang,
                        action: 'postLots',
                        url: `https://autohelperbot.com/copart_lots?autohelperbot_app=1.0&json=${true}`
                    }, function(response) {
                        if (chrome.runtime.lastError) {
                            console.error('Error:', chrome.runtime.lastError.message);
                            return;
                        }
                        onDataCatalog(response.data);

                    });

                }

            }
        }

    }

}, 1000);

var block = '<div class="formbox sale-info-box" id="autohelperbot_details">\
      <div class="sales-info-header">\
         <h3 class="lot-number nmt bg-lblue white" style="background-color: #373d5d;">AutohelperBot</h3>\
         <div class="sales-info-content">\
            <div class="lot-details-content row">\
               <div class="col-md-12">\
                  <div class="lot-details-inner">\
                     &nbsp;&nbsp;Loading data...\
                  </div>\
               </div>\
            </div>\
         </div>\
      </div>\
   </div>';


var timer2 = setInterval(async function(){
    // .bid-information
    if($('.bid-information').length > 0 && $('.bid-information').hasClass('autohelperbot') == false && $('.autohelperbot').length == 0) {
        $('.bid-information').addClass('autohelperbot');
        $('h3[data-uname="lotdetailSaleinformationlabel"]').addClass('autohelperbot');
        var lot_id = window.location.href.match(/\/lot\/([0-9]+)/)[1];

        if(lot_id > 0) {
            $('<iframe id="myIframe" sandbox="allow-same-origin allow-scripts"/>')
                .attr('src', `https://autohelperbot.com/copart_lot/${lot_id}/?type=ns&lang=${userLang}&autohelperbot_app=1.0&jsonp=${false}`)
                .css({
                    'width': '100%',
                    'border': 'none',
                })
                .appendTo('.bid-information');

            window.addEventListener('message', function(event) {
                if (event.data.type === 'SET_IFRAME_HEIGHT') {
                    var iframe = document.getElementById('myIframe');
                    if (iframe) {
                        iframe.style.height = event.data.height + 'px';
                    }
                }
            }, false);
        }

        // h3[data-uname="lotdetailSaleinformationlabel"]
    } else if($('h3[data-uname="lotdetailSaleinformationlabel"]').length > 0 && $('h3[data-uname="lotdetailSaleinformationlabel"]').hasClass('autohelperbot') == false && $('.autohelperbot').length == 0) {
        $('h3[data-uname="lotdetailSaleinformationlabel"]').addClass('autohelperbot');
        $('.sale-info-box').addClass('autohelperbot');
        var lot_id = window.location.href.match(/\/(\d+)~/)[1];

        if(lot_id > 0) {
            if($('#cfw-container').length > 0) {
                $(block).insertBefore('#cfw-container');
            } else {
                if($('.right.bid-information div.panel:last').length > 0) {
                    $(block).insertBefore('.right.bid-information div.panel:last');
                } else {
                    $(block).insertBefore($('h3[data-uname="lotdetailSaleinformationlabel"]').parent().parent());
                }
            }
            $('<iframe id="myIframe" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"/>')
                .attr('src', 'https://autohelperbot.com/copart_lot/'+ lot_id +'/?lang='+ userLang +'&jsonp=false&v=2&autohelperbot_app=1.0&')
                .css({
                    'width': '100%',
                    'border': 'none',
                })
                .insertAfter('.sale-information-block');

            window.addEventListener('message', function(event) {
                if (event.data.type === 'SET_IFRAME_HEIGHT') {
                    var iframe = document.getElementById('myIframe');
                    if (iframe) {
                        iframe.style.height = event.data.height + 'px';
                    }
                }
            }, false);
        }

        //.bid-information-section.cprt-panel
    } else if($('.bid-information-section.cprt-panel').length > 0 && $('.bid-information-section.cprt-panel').hasClass('autohelperbot') == false && $('.autohelperbot').length == 0) {
        console.log('[AHB] 1');
        $('.bid-information-section.cprt-panel').addClass('autohelperbot');
        var lot_id = window.location.href.match(/\/lot\/([0-9]+)/)[1] || window.location.href.match(/\/(\d+)~/)?.[1];

        console.log('[AHB] lot_id', lot_id);
        if(lot_id > 0) {
            $('<iframe id="myIframe" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"/>')
                .attr('src', 'https://autohelperbot.com/copart_lot/'+ lot_id +'/?lang='+ userLang +'&v=2&autohelperbot_app=1.0&jsonp=false')
                .css({
                    'width': '100%',
                    'border': 'none',
                })
                .insertAfter('.bid-information-section.cprt-panel');

            console.log('[AHB] myIframe', document.getElementById('myIframe'));

            window.addEventListener('message', function(event) {
                if (event.data.type === 'SET_IFRAME_HEIGHT') {
                    var iframe = document.getElementById('myIframe');
                    if (iframe) {
                        iframe.style.height = event.data.height + 'px';
                    }
                }
            }, false);
        }
    } else if($('.vehicle-assessment.ng-star-inserted').length > 0 && $('.vehicle-assessment.ng-star-inserted').hasClass('autohelperbot') == false && $('.autohelperbot').length == 0) {
        console.log('[AHB] 1');
        $('.vehicle-assessment.ng-star-inserted').addClass('autohelperbot');
        var lot_id = window.location.href.match(/\/lot\/([0-9]+)/)[1] || window.location.href.match(/\/(\d+)~/)?.[1];

        console.log('[AHB] lot_id', lot_id);
        if(lot_id > 0) {
            $('<iframe id="myIframe" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"/>')
                .attr('src', 'https://autohelperbot.com/copart_lot/'+ lot_id +'/?lang='+ userLang +'&v=2&autohelperbot_app=1.0&jsonp=false')
                .css({
                    'width': '100%',
                    'border': 'none',
                })
                .insertBefore('.vehicle-assessment.ng-star-inserted');

            console.log('[AHB] myIframe', document.getElementById('myIframe'));

            window.addEventListener('message', function(event) {
                if (event.data.type === 'SET_IFRAME_HEIGHT') {
                    var iframe = document.getElementById('myIframe');
                    if (iframe) {
                        iframe.style.height = event.data.height + 'px';
                    }
                }
            }, false);
        }
    }
}, 1000);

var timer_IAAI_lots = setInterval(async function(){
    var found_lots = '';

    if($('#ResultFoundOnPage').length > 0) {
        if($('#ListingGrid .table-body .table-row').length > 0 && !$('#ListingGrid .table-body').hasClass('autohelperbot')) {
            $('#ListingGrid .table-body').addClass('autohelperbot');

            var lot_ids = {};

            $('#ListingGrid .table-body .table-cell--data').each((k, x) => {
                if( parseInt($(x).find('h4 a').attr('name')) > 0 ) {
                    lot_ids[ parseInt($(x).find('h4 a').attr('name')) ] = parseInt($(x).find('.table-cell--inner .table-cell:first .data-list__item:first .data-list__value').text());
                } else {
                    lot_ids.push( parseInt($(x).find('.table-cell--inner .table-cell:first .data-list__item:first .data-list__value').text()) );
                }
            });

            found_lots = {
                lots: JSON.stringify(lot_ids)
            }
        }
    }

    if($('div.table.table--image-view').length > 0 && !$('div.table.table--image-view').hasClass('autohelperbot')) {
        $('div.table.table--image-view').addClass('autohelperbot');

        var lot_ids = $.makeArray($('.table-cell--data')).map(x => ( parseInt($(x).find('.row:first .data-list__item:first .data-list__value').text()) ));
        found_lots = {
            lots: JSON.stringify(lot_ids)
        }
    }

    if($('div.table.table-mobile').length > 0 && !$('div.table.table-mobile').hasClass('autohelperbot')) {
        $('div.table.table-mobile').addClass('autohelperbot');

        var lot_ids = $.makeArray($('.table-row-main')).map(x => ( parseInt($(x).find('.table-cell--left div').attr('class').replace('text-center mb-5 PrebidStatusText-', '')) ));
        found_lots = {
            lots: JSON.stringify(lot_ids)
        }
    }

    if($('table.table.table--table-view').length > 0 && !$('table.table.table--table-view').hasClass('autohelperbot')) {
        $('table.table.table--table-view').addClass('autohelperbot');

        var lot_ids = $.makeArray($('.table.table.table--table-view tbody tr')).map(x => ( parseInt($(x).find('td:nth-child(3) a.link').text()) ));
        found_lots = {
            lots: JSON.stringify(lot_ids)
        }
    }

    if(found_lots == '' && $('.table-cell--inner.table-row-border').length > 0 && !$('.table-cell--inner.table-row-border').hasClass('autohelperbot')) {
        $('.table-cell--inner.table-row-border').addClass('autohelperbot');

        var lot_ids = $.makeArray($('.table-cell--inner.table-row-border')).map(x => {
            var lotNumber = $(x).find('.table-cell--data .data-list__value:first').text() ||
                $(x).find('h4 a').attr('name') ||
                $(x).find('[data-lot-id]').attr('data-lot-id');
            return parseInt(lotNumber);
        }).filter(x => x > 0);

        if(lot_ids.length > 0) {
            found_lots = {
                lots: JSON.stringify(lot_ids)
            }
        }
    }

    if(found_lots != '') {
        chrome.runtime.sendMessage({
            found_lots: found_lots,
            userLang: userLang,
            action: 'postLots',
            url: 'https://autohelperbot.com/iaai_lots?lang='+ userLang +'&autohelperbot_app=1.0&json=true'
        }, function(response) {
            if (chrome.runtime.lastError) {
                console.error('Error:', chrome.runtime.lastError.message);
                return;
            }
            if (response && response.data) {
                onDataCatalog(response.data);
            } else if (response && response.error) {
                console.error('Failed to receive data:', response.error);
            } else {
                console.error('Unknown error occurred');
            }
        });
    }
}, 1000);

var timer_IAAI_lot = setInterval(async function(){
    if ($('.action-area').length > 0 && $('.action-area').hasClass('autohelperbot') == false && $('.autohelperbot').length == 0) {
        $('.action-area').addClass('autohelperbot');
        $('h3[data-uname="lotdetailSaleinformationlabel"]').addClass('autohelperbot');
        var lot_id = window.location.href.toLocaleLowerCase().match(/\/vehicledetail\/(\d+)/)[1];
        if(lot_id > 0){
            $('<iframe id="myIframe" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"/>')
                .attr('src', `https://autohelperbot.com/iaai_lot/${lot_id}/?type=ns&lang=${userLang}&autohelperbot_app=1.0&jsonp=${false}`)
                .css({
                    'width': '100%',
                    'border': 'none',
                })
                .appendTo('.action-area');

            window.addEventListener('message', function(event) {
                if (event.data.type === 'SET_IFRAME_HEIGHT') {
                    var iframe = document.getElementById('myIframe');
                    if (iframe) {
                        iframe.style.height = event.data.height + 'px';
                    }
                }
            }, false);
        }
    }
}, 1000)
