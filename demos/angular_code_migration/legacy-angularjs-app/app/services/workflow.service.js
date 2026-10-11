(function () {
  "use strict";

  angular.module("legacyJiraBoard").service("Workflow", function () {
    var transitions = {
      todo: ["in-progress", "blocked"],
      "in-progress": ["review", "blocked"],
      review: ["done", "in-progress"],
      blocked: ["todo", "in-progress"],
      done: ["review"]
    };

    this.canMove = function (issue, targetStatus) {
      return transitions[issue.status].indexOf(targetStatus) !== -1;
    };

    this.availableTargets = function (issue, lanes) {
      return lanes.filter(function (lane) {
        return lane.status !== issue.status && transitions[issue.status].indexOf(lane.status) !== -1;
      });
    };

    this.recalculateProgress = function (issue) {
      var done = issue.checklist.filter(function (item) {
        return item.done;
      }).length;
      issue.progress = Math.round((done / issue.checklist.length) * 100);
      return issue.progress;
    };
  });
})();
