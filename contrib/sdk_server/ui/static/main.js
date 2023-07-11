// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Active selection border styles. These don't need to be custom classes
// since they're just combinations of bootstrap classes.
const topSelectorStyle = `border-black border-3 border-start-0
    border-end-0 border-top-0`;
const bottomSelectorStyle = `border-top-0 border-start-0
    border-end-0 border-light border-2`;

//maps repo status indicators to labels/colors
const head_status = {
    "-": ["No change", "secondary"],
    "A": ["Added", "success"],
    "M": ["Modified", "success"],
    "D": ["Deleted", "danger"],
    "R": ["Renamed", "secondary-emphasis"],
    "C": ["Copied", "secondary-emphasis"],
    "T": ["Mode changed", "secondary-emphasis"],
    "U": ["Unmerged", "danger"],
}

const working_status = {
    "-": ["New", "success"],
    "m": ["Modified", "success"],
    "d": ["Deleted", "danger"]
}


//Panel selection/styling functions
function showPackages() {
    $("#packagesPanel").show();
    $("#sysrootsPanel").hide();

    $("#showPackages").addClass(topSelectorStyle);
    $("#showSysroots").removeClass(topSelectorStyle);
}

function showSysroots() {
    $("#packagesPanel").hide();
    $("#sysrootsPanel").show();

    $("#showSysroots").addClass(topSelectorStyle);
    $("#showPackages").removeClass(topSelectorStyle);
}

function showLogs() {
    $("#logsPanel").show()
    $("#repoPanel").hide()

    $("#showLogs").addClass(bottomSelectorStyle)
    $("#showRepo").removeClass(bottomSelectorStyle)
}

function showRepo() {
    $("#logsPanel").hide()
    $("#repoPanel").show()

    $("#showRepo").addClass(bottomSelectorStyle)
    $("#showLogs").removeClass(bottomSelectorStyle)
}

function liveLogPopulator(commandName, logText, now){
    //log panel already exists
    if ($("#" + now.format("x") + "liveLog").length){
        $("#log" + now.format("x") + "Text").html(logText);
    }
    else{
        //Create it
        $("#logsList").html(
            `
            <li class = "row bg-dark" id = "` + now.format("x") + `liveLog">
                <div class="col-8"><p2 class = "small text-light ms-2"><code class = "text-light">`+commandName+`</code></p2></div>
                <div class = "col-2">
                  <a href="#log`+now.format("x")+`" data-bs-toggle="collapse" role="button" 
                    aria-controls="log`+now.format("x")+`" aria-expanded="false" 
                    class = "d-flex align-items-center log-expander link-underline 
                      link-underline-opacity-0 classic-link">
                    View Log 
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-caret-right-fill" viewBox="0 0 16 16">
                      <path d="m12.14 8.753-5.482 4.796c-.646.566-1.658.106-1.658-.753V3.204a1 1 0 0 1 1.659-.753l5.48 4.796a1 1 0 0 1 0 1.506z"/>
                    </svg>
                  </a>
                  
                </div>
                <div class="col"><p2 class = "small text-light ms-2">`+now.format("MMM D h:mma")+`</p2></div>
                <div class = "bg-black small overflow-auto border-top collapse log-box" id = "log`+now.format("x")+`">
                  <code class = "small text-light log-text" id = "log`+now.format("x")+`Text" >`+logText+`</code>
                </div>
              </li>
            ` + $("#logsList").html()  
        )
        //Rotates the log expander arrow
        $(".log-expander").on('click', function () {
            $(this).children("svg").toggleClass("rotate-log-button")
        })
    }
}

//Makes request to gRPC server via python routes and generates HTML
//for repo files dynamically.
function populateRepoFiles() {
    $.ajax({
        url: "/repo-refresh",
        type: "POST",

        success: function (response) {

            $("#repoProject").removeClass("placeholder bg-light me-3");
            $("#repoBranch").removeClass("placeholder bg-light me-3");

            $("#repoProject").html(response.project);
            $("#repoBranch").html(response.branch);

            var filesHTML = "";


            response.files.forEach(function (file) {
                filesHTML += `
            <li class="row bg-dark border-top border-black
                    p-0 m-0 align-items-center">
                <div class="col-6 text-break ms-2">
                <p2 class = "small text-light">` + file.file + `</p2>
                </div>
                <div align = "center" class="col">
                <p2 class = "small text-` + head_status[file.head][1] + `">
                    ` + head_status[file.head][0] + `
                </p2>
                </div>
                <div align = "center" class="col">
                <p2 class = "small text-` + working_status[file.working][1] +
                    `">
                    ` + working_status[file.working][0] + `
                </p2>
                </div>
            </li>
            `
            })

            $("#repoFilesList").html(filesHTML);
        },
        error: function (xhr) {
            console.log("failure");
        }
    });
}

function populatePackages(board = "") {

    $.ajax({
        url: "/get-packages",
        type: "POST",
        data: JSON.stringify({
            board: board
        }),
        contentType: "application/json",

        success: function (response) {
            allPackagesHTML = "";
            jQuery.each(response, function (board, packages) {

                if (packages.length > 0) {
                    allPackagesHTML += `<ul class="p-0 board-package-list" 
                        id= "`+ board + `-package-list">
                    `
                    packages.forEach(function (pack) {
                        allPackagesHTML +=
                        `<li class="row bg-dark border-top border-black p-0 m-0 align-items-center">
                          <div class="col-7"><p2 class = "small text-light m-4">` + pack.name + `</p2></div>
                          <div class="col-2 d-flex">
                            <p2 class = "col small text-success">+` + pack.plus + `</p2>
                            <p2 class = "col small text-danger">-`  + pack.minus + `</p2>
                          </div>
                          <div class="col">
                            <button type="button" class="small btn btn-success btn-sm pt-0 pb-0 mt-1 mb-1" >Build</button>
                            <button type="button" class="small btn btn-secondary btn-sm pt-0 pb-0" data-bs-toggle="modal" 
                              data-bs-target="#` + pack.name.replace("/", "-") + `-info-modal" >Info</button>
                            <button type="button" class="small btn btn-danger btn-sm pt-0 pb-0 workon-stop"
                            id = ` + pack.name + `>Stop</button>
                          </div>              
                        </li>
                        
                        <div class="modal fade" id="` + pack.name.replace("/", "-") + `-info-modal" tabindex="-1" 
                            aria-labelledby="exampleModalLabel" aria-hidden="true">
                          <div class="modal-dialog">
                            <div class="modal-content bg-dark">
                              <div class="modal-header">
                                <h1 class="modal-title fs-5 text-light">Package Info</h1>
                                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                              </div>
                              <div class="modal-body">
                                
                                <p2 class = "row text-white-50 ms-1">Package Name</p2>
                                <p2 class = "row text-light ms-1">`+pack.name+`</p2>
                            

                                <p2 class = "row text-white-50 ms-1 mt-4">Repositor`+(pack.repo.length > 1 ? `ies` : `y`)+`</p2>
                                `+
                                    pack.repo.reduce(function(base, curr){
                                        return base += `<p2 class = "row text-light ms-1"">`+curr+`</p2>`
                                    }, "")
                                +`
                            
                                <p2 class = "row text-white-50 ms-1 mt-4">Source Director`+(pack.source.length > 1 ? `ies` : `y`)+`</p2>
                                `+
                                    pack.source.reduce(function(base, curr){
                                        return base += `<p2 class = "row text-light ms-1"">`+curr+`</p2>`
                                    }, "")
                                +`
                                
                              </div>
                              <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                              </div>
                            </div>
                          </div>
                        </div>`

                    })

                    allPackagesHTML += `</ul>`
                }
                else {
                    console.log("here")
                    allPackagesHTML += `
                    <row class="board-package-list small text-light bg-dark border-top border-black p-0 m-0"
                      id= `+ board + `-package-list>
                        <p2 class = "ps-5">No packages to display for this board...</p2>
                      </row>`
                }
            })
            if(!board){
                $("#allBoardPackages").html(allPackagesHTML);
            }else{
                $(`#`+ board + `-package-list`).remove()
                $("#allBoardPackages").html($("#allBoardPackages").html() + allPackagesHTML);
            }
            

            //Packages board dropdown selection logic
            var boardName = $('#boardSelector li a.active').html()
            $('#boardSelectorTitle').html(boardName);
            $('.board-package-list').hide()
            $('#' + boardName + "-package-list").show()

            $(".workon-stop").on('click', workonStop);
            $('#boardSelector li').on('click', changeBoardSelectorActive)
        },

        failure: function (xhr) {
            console.log("failure");
        }
    })
}



function confirmDelete() {
    var btnDisabled = $("#deleteSubmit").attr("disabled");

    if (typeof btnDisabled == 'undefined' || btnDisabled == false) {
        $("#deleteSubmit").attr("disabled", "");
    }
    else {
        $("#deleteSubmit").removeAttr("disabled");
    }
}

function changeBoardSelectorActive() {
    var boardName = $(this).find('a').html()

    $('#boardSelectorTitle').html(boardName);
    $('.board-list-item').removeClass('active');
    $(this).find('a').addClass('active');

    $('.board-package-list').hide()
    $('#' + boardName + "-package-list").show()
}

function workonStart() {

    var board = $("#addPackageBoardSelect").select2("data")[0].text;
    var pack = $("#addPackagePackageSelect").select2("data")[0].text;
    $.ajax({
        url: "/workon-start",
        type: "get",
        data: {
            board: board,
            package: pack
        },

        success: function (response) {
            console.log("success");
            populatePackages(board = board);
        },
        error: function (xhr) {
            console.log("failure");
        }
    });
}

//Will make cros_workon stop request via Flask routes.
function workonStop() {
    var package = this.id;
    var button = this;

    var board = $(this).parents("ul")[0].id;
    board = board.substring(0, board.length - 13)

    $(button).addClass("disabled");

    $.ajax({
        url: "/workon-stop",
        type: "get",
        data: {
            board: board,
            package: package
        },

        success: function (response) {
            console.log("success");
            populatePackages(board = board);
        },
        error: function (xhr) {
            console.log("failure");
        }
    });
}

function updateChroot(){

    $("#updateChrootSubmit").addClass("disabled");

    window.onbeforeunload = function() {
        return true;
    };

    buildSource = $('#buildSourceCheck').is(':checked');
    toolchainChanged = $("#toolchainChangedCheck").is(":checked");
    toolchainTargets = []
    $("#updateToolchainTargets").select2("data").forEach(function(board){
        toolchainTargets.push(board.text);
    })

    now = moment()

    $.ajax({
        url: "/update-chroot",
        type: "POST",
        data: JSON.stringify({
            buildSource: buildSource,
            toolchainChanged: toolchainChanged,
            toolchainTargets: toolchainTargets
        }),
        contentType: "application/json",
        
        success: function(response){
            console.log("success");
            console.log(response)

            $("#updateChrootSubmit").removeClass("disabled");
            window.onbeforeunload = null;
        },

        error: function(xhr){
            console.log("failure");
            console.log(xhr)
            $("#updateChrootSubmit").removeClass("disabled");
        },

        xhrFields: {
            onprogress: function(e){

                liveLogPopulator(
                    "Update Chroot", 
                    e.currentTarget.response, 
                    now
                )
            }
        }
    })
}

function replaceChroot(){
    $("#replaceChrootSubmit").addClass("disabled");

    window.onbeforeunload = function() {
        return true;
    };

    bootstrap = $("#replaceBootstrap").is(":checked");
    noUseImage = $("#replaceNoUseImage").is(":checked");
    version = $("replaceSDKVersion").value;

    $.ajax({
        url: "/replace-chroot",
        type: "POST",
        data: JSON.stringify({
            bootstrap: bootstrap,
            noUseImage: noUseImage,
            version: version
        }),
        dataType: "json",
        contentType: "application/json",

        success: function(response){
            $("#replaceChrootSubmit").removeClass("disabled");
            location.reload();
            window.onbeforeunload = null;
        },

        error: function(xhr){
            console.log("failure");
        },

        xhrFields: {
            onprogress: function(e){

                liveLogPopulator(
                    "Replace Chroot", 
                    e.currentTarget.response, 
                    now
                )
            }
        }

    })
}

function buildPackages(){
    $("#buildPackagesSubmit").addClass("disabled");

    window.onbeforeunload = function() {
        return true;
    };

    chrootCurrent = $("#buildChrootCurrent").is(":checked");
    replace = $("#buildReplace").is(":checked");
    toolchainChanged = $("#buildToolchainChanged").is(":checked");
    CQPrebuilts = $("#buildCQPrebuilts").is(":checked");
    buildTarget = $("#buildBuildTarget").select2("data")[0].text;
    compileSource = $("#buildCompileSource").is(":checked");
    dryrun = $("#buildDryrun").is(":checked");
    workon = $("#buildWorkon").is(":checked");

    now = moment();

    $.ajax({
        url: "/build-packages",
        type: "POST",
        data: JSON.stringify({
            chrootCurrent: chrootCurrent,
            replace : replace,
            toolchainChanged : toolchainChanged,
            CQPrebuilts: CQPrebuilts,
            buildTarget: buildTarget,
            compileSource: compileSource,
            dryrun: dryrun,
            workon: workon
        }),

        contentType: "application/json",

        success: function(response){
            $("#buildPackagesSubmit").removeClass("disabled");
            window.onbeforeunload = null;
        },

        error: function(xhr){
            console.log("failure");
        },

        xhrFields: {
            onprogress: function(e){

                liveLogPopulator(
                    "Build Packages", 
                    e.currentTarget.response, 
                    now
                )
            }
        }

    })
}

$(document).ready(function () {
    //Show default active panels (logs/packages)
    showPackages();
    showLogs();

    //Fetch repo and workon data
    populateRepoFiles();
    populatePackages();

    //Activates tooltips
    const tooltipTriggerList = document.querySelectorAll(
        '[data-bs-toggle="tooltip"]'
    )
    const tooltipList = [...tooltipTriggerList].map(
        tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl)
    )

    

    //Activates select2s (the large dropdowns with search bars)
    $(".update-select").select2({
        dropdownParent: $("#updateChrootModal"),
        theme: 'bootstrap-5',
        width: '100%',
        placeholder: "Select a board..."
    });
    $(".add-package-select").select2({
        dropdownParent: $("#addPackagesModal"),
        theme: 'bootstrap-5'
    });
    $(".build-packages-select").select2({
        dropdownParent: $("#buildPackagesModal"),
        theme: 'bootstrap-5',
        width: '100%'
    });

    //Button listeners
    $("#addPackageSubmit").on("click", workonStart);
    $("#confirmDelete").on('click', confirmDelete);
    $("#showPackages").on('click', showPackages);
    $("#showSysroots").on('click', showSysroots);
    $("#showLogs").on('click', showLogs);
    $("#showRepo").on('click', showRepo);
    $("#repoStatusRefresh").on("click", populateRepoFiles);
    $("#updateChrootSubmit").on("click", updateChroot);
    $("#replaceChrootSubmit").on("click", replaceChroot);
    $("#buildPackagesSubmit").on("click", buildPackages);

    

    
});