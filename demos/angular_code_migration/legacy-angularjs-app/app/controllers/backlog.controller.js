(function () {
  "use strict";

  angular.module("legacyJiraBoard").controller("BacklogController", function ($timeout) {
    var vm = this;

    vm.epics = [
      {
        id: "EPIC-21",
        name: "Customer portal refresh",
        description: "Replace legacy account pages with responsive workflows."
      },
      {
        id: "EPIC-34",
        name: "Billing reliability",
        description: "Reduce failed invoices and add manual retry controls."
      },
      {
        id: "EPIC-55",
        name: "Audit exports",
        description: "Give enterprise admins downloadable compliance evidence."
      }
    ];

    vm.promoteEpic = function (epic) {
      epic.promoting = true;
      $timeout(function () {
        epic.promoting = false;
        epic.promoted = true;
      }, 500);
    };
  });
})();
