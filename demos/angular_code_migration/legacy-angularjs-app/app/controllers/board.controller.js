(function () {
  "use strict";

  angular.module("legacyJiraBoard").controller("BoardController", function (BoardApi, Workflow) {
    var vm = this;

    vm.project = { name: "Loading", members: [] };
    vm.issues = [];
    vm.lanes = [];
    vm.selected = null;
    vm.filters = JSON.parse(window.localStorage.getItem("boardFilters") || "{\"query\":\"\",\"assignee\":\"\"}");

    vm.refresh = function () {
      return BoardApi.loadBoard().then(function (board) {
        vm.project = board.project;
        vm.issues = board.issues;
        vm.lanes = board.lanes;
      });
    };

    vm.persistFilters = function () {
      window.localStorage.setItem("boardFilters", JSON.stringify(vm.filters));
    };

    vm.selectIssue = function (issue) {
      vm.selected = issue;
    };

    vm.assigneeName = function (assigneeId) {
      var member = vm.project.members.find(function (candidate) {
        return candidate.id === assigneeId;
      });
      return member ? member.name : "Unassigned";
    };

    vm.moveIssue = function (issue, targetStatus) {
      if (!Workflow.canMove(issue, targetStatus)) {
        window.alert("Invalid workflow transition from " + issue.status + " to " + targetStatus);
        return;
      }

      issue.status = targetStatus;
      return BoardApi.moveIssue(issue.id, targetStatus).then(function (saved) {
        angular.extend(issue, saved);
      });
    };

    vm.saveIssue = function (issue) {
      return BoardApi.saveIssue(issue);
    };

    vm.recalculateProgress = function (issue) {
      Workflow.recalculateProgress(issue);
      vm.saveIssue(issue);
    };

    vm.targetsFor = function (issue) {
      return Workflow.availableTargets(issue, vm.lanes);
    };

    vm.refresh();
  });
})();
