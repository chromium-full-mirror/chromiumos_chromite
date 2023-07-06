// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Active selection border styles. These don't need to be custom classes
// since they're just combinations of bootstrap classes.
const topSelectorStyle = `border-black border-3 border-start-0
    border-end-0 border-top-0`;
const bottomSelectorStyle = `border-top-0 border-start-0
    border-end-0 border-light border-2`;

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

//Makes request to gRPC server via python routes and generates HTML
//for repo files dynamically.
function populateRepoFiles() {
    $.ajax({
        url: "/repo-refresh",
        type: "POST",

        success: function (response) {

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

function addPackages() {
    var board = $("#addPackageBoardSelect").select2("data");
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
            location.reload()
        },
        error: function (xhr) {
            console.log("failure");
        }
    });
}

$(document).ready(function () {
    //Show default active panels (logs/packages)
    showPackages();
    showLogs();
    populateRepoFiles();

    //Activates tooltips
    const tooltipTriggerList = document.querySelectorAll(
        '[data-bs-toggle="tooltip"]'
    )
    const tooltipList = [...tooltipTriggerList].map(
        tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl)
    )

    //Packages board dropdown selection logic
    var boardName = $('#boardSelector li a.active').html()
    $('#boardSelectorTitle').html(boardName);
    $('.board-package-list').hide()
    $('#' + boardName + "-package-list").show()

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
    $("#addPackageSubmit").on("click", addPackages);
    $("#confirmDelete").on('click', confirmDelete);
    $("#showPackages").on('click', showPackages);
    $("#showSysroots").on('click', showSysroots);
    $('#boardSelector li').on('click', changeBoardSelectorActive)
    $(".workon-stop").on('click', workonStop);
    $("#showLogs").on('click', showLogs);
    $("#showRepo").on('click', showRepo);
    $("#repoStatusRefresh").on("click", populateRepoFiles)

    //Rotates the log expander arrow
    $(".log-expander").on('click', function () {
        $(this).children("svg").toggleClass("rotate-log-button")
    })
});