var queryType= "";

function TransitionSelector(){
	this.element = null;
    this.datatype = null
	this.dataset = null;
	this.density = null;
	this.wavelengthMin = null;
	this.wavelengthMax = null;
	this.transition = null;
	this.temperature = null;	
	this.controller = null;
	this.method = null;
	this.targetFormElement = null;
	this.format = null;	
  this.afterUpdate = null
}

var selector = null;

function getSelector(){
	if(selector == null)
		selector  = new TransitionSelector();
	else{
		selector.element = null;
		selector.dataset = null;
		selector.density = null;
		selector.temperature = null;
		selector.transition = null;
		selector.controller = null;
		selector.method = null;
		selector.targetFormElement = null;	
		selector.wavelengthMin = null;
		selector.wavelengthMax = null;
		selector.queryType = null;
	}	
	return selector;
}

/**
 * 	elementId : id of the element modified in the form
 *  fieldId : id of the element whose content will be updated
 *  method : controller method called
 *  parameter : parameter taken by the controller
 *  
 */
function simpleUpdate(selector){
    var request = 'module=stark_b&action='+selector.controller+':'+selector.method;

	if(selector.element !== null)
		request += '&elementId='+selector.element;
        
	if(selector.datatype !== null)
		request += '&datatype='+selector.datatype;
		
	if(selector.dataset !== null)
		request += '&datasetId='+selector.dataset;
		
	if(selector.density !== null){
		request += '&density='+encodeURIComponent(selector.density);
	}
		
	if(selector.transition !== null)
		request += '&transition='+encodeURIComponent(selector.transition);
		
	if(selector.temperature !== null)
		request += '&temperature='+encodeURIComponent(selector.temperature);
		
	if(selector.wavelengthMin !== null)
		request += '&wavelengthMin='+encodeURIComponent(selector.wavelengthMin);
		
	if(selector.wavelengthMax !== null)
		request += '&wavelengthMax='+encodeURIComponent(selector.wavelengthMax);
		
	if(selector.queryType !== null)
		request += '&queryType='+selector.queryType;
		
	if(selector.format !== null)
		request += '&format='+selector.format;

    var requester = getRequester();
    requester.onreadystatechange=function(){
        var response = '';
        if(4== requester.readyState){
            if(200 == requester.status){
                response = requester.responseText;
            }else{
                response = "error : "+requester.status;
            }
            document.getElementById(selector.targetFormElement).innerHTML = response;
            if(selector.afterUpdate !== null)
              selector.afterUpdate();
        }
    }
    requester.open('POST', 'index.php', true);
    requester.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
    requester.send(request);   	
}

function densityUpdater(){
	document.getElementById('temperatures').innerHTML = '';
	document.getElementById('transitions').innerHTML = '';
		
	var selector = getSelector();
	selector.targetFormElement = 'densities';
	selector.controller = 'querypage';
	selector.method = 'densities';
	selector.dataset = document.getElementById('dataset').options[document.getElementById('dataset').selectedIndex].value;

	if(selector.dataset == -1){
		document.getElementById('densities').innerHTML = '';	
		document.getElementById('temperatures').innerHTML = '';	
		document.getElementById('transitions').innerHTML = '';	
	}else 	
		simpleUpdate(selector);	
}

function interpolatedDensityUpdater(){
	var selector = getSelector();
	selector.targetFormElement = 'interpolatedDensities';
	selector.controller = 'querypage';
	selector.method = 'interpolatedDensities';
	selector.dataset = document.getElementById('dataset').options[document.getElementById('dataset').selectedIndex].value;
	simpleUpdate(selector);	
}

function transitionUpdater(){
	var selector = getSelector();		
	selector.targetFormElement = 'transitions';
	selector.controller = 'querypage';
	selector.method = 'transitions';
	selector.density = getDensity();
	
	if(selector.density == -1){
		document.getElementById('temperatures').innerHTML = '';	
		document.getElementById('transitions').innerHTML = '';	
	}else 	
		simpleUpdate(selector);	
}

function temperatureUpdaterFromDensity(){
	queryType='density';
	var selector = getSelector();		
	selector.targetFormElement = 'temperatures';
	selector.controller = 'querypage';
	selector.method = 'temperatures';
	selector.transition = document.getElementById('transition').options[document.getElementById('transition').selectedIndex].value;	
	
	if(selector.transition == -1){
		document.getElementById('temperatures').innerHTML = '';	
	}else 	
		simpleUpdate(selector);		
}

function temperatureUpdaterFromWavelength(){
	queryType='wavelength';
	var selector = getSelector();		
	selector.targetFormElement = 'temperatures';
	selector.controller = 'querypage';
	selector.method = 'temperatures';
	selector.wavelengthMin = document.getElementById('wavelengthMin').value;
	selector.wavelengthMax = document.getElementById('wavelengthMax').value;	
	if(selector.transition == -1){
		document.getElementById('temperatures').innerHTML = '';	
	}else 	
		simpleUpdate(selector);		
}

function getDensity(){
	var density = document.getElementById('density').options[document.getElementById('density').selectedIndex].value;
	if(density == 'other')
		density = document.getElementById('userDensity').value;
	return density;	
	
}

function wavelengthResultUpdater(){
	var selector = getSelector();	
	selector.targetFormElement = 'results';		
	selector.controller = 'querypage';
	selector.method = 'query';
	selector.format = 'html';
	selector.queryType='wavelength';
	selector.wavelengthMin = document.getElementById('wavelengthMin').value;
	selector.wavelengthMax = document.getElementById('wavelengthMax').value;	  
  selector.afterUpdate = function(){bind_double_scrollbar("shiftings");bind_double_scrollbar("fits");};  
	simpleUpdate(selector);	
}

function densityResultUpdater(){
	var selector = getSelector();	
	selector.targetFormElement = 'results';		
	selector.controller = 'querypage';
	selector.method = 'query';
	selector.format = 'html';
	selector.queryType=queryType;
	selector.temperature = document.getElementById('temperature').options[document.getElementById('temperature').selectedIndex].value;	
  selector.afterUpdate = function(){bind_double_scrollbar("shiftings");bind_double_scrollbar("fits");};  
	simpleUpdate(selector);	
}

function interpolatedDensityResultUpdater(){
	var selector = getSelector();	
	selector.targetFormElement = 'results';		
	selector.controller = 'querypage';
	selector.method = 'query';
	selector.format = 'html';
	selector.queryType='interpolatedDensity';
	selector.density = document.getElementById('interpolatedDensity').value;
  selector.afterUpdate = function(){bind_double_scrollbar("shiftings");bind_double_scrollbar("fits");};  
	simpleUpdate(selector);	
}

function densityInterpolation(){
	var density = document.getElementById('density');
	if(parseFloat(density.options[density.length-1].value) < parseFloat(document.getElementById('userDensity').value)){
		alert('interpolation impossible. Density value is too high');
		return false;
	}
}

function hide_table(trigger, id){
    if($('#'+id).css('display') == 'none'){
       $('#'+id).css('display', '');
       $('#'+trigger).html('hide table');
    }else{
        $('#'+id).css('display', 'none');
        $('#'+trigger).html('show table');
    }
}

function bind_double_scrollbar(zone_id){
  $("#"+ zone_id +" .wmd-view-topscroll").bind("scroll", function() {
    $("#"+ zone_id +" .wmd-view").scrollLeft($("#"+ zone_id +" .wmd-view-topscroll").scrollLeft());  
  });
  
  $("#"+ zone_id +" .wmd-view").bind('scroll', function() {
    $("#"+ zone_id +" .wmd-view-topscroll").scrollLeft($("#"+ zone_id +" .wmd-view").scrollLeft()); 
  });   
}

$(document).ready(function () {  
    
    $(document).on('click', '#hide_fits',function(){hide_table("hide_fits", "fits");});
    $(document).on('click', '#hide_shiftings',function(){hide_table("hide_shiftings", "shiftings");});
    $('#dataset').change(function(){densityUpdater()});    
    

   /* var bind_shifting_scroll_event = false;
    $(document).on('mouseenter', '#shiftings', function() {
      console.log($("#shiftings input[name=binded]").val());
      if(!bind_shifting_scroll_event){
        bind_double_scrollbar("shiftings");
      }
      bind_shifting_scroll_event = true;
    });   
    
    var bind_fit_scroll_event = false;
    $(document).on('mouseenter', '#fits', function() {
      if(!bind_fit_scroll_event){
        bind_double_scrollbar("fits");
      }
      bind_fit_scroll_event = true;
    });  */  
});
