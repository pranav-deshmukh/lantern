(function () {
  "use strict";

  angular.module("legacyJiraBoard").directive("swimlane", function () {
    return {
      restrict: "E",
      scope: {
        lane: "=",
        issues: "=",
        onMove: "&",
        onSelect: "&"
      },
      template:
        '<section class="lane">' +
        '  <div class="lane-header">' +
        '    <h2>{{ lane.label }}</h2>' +
        '    <strong>{{ issues.length }}</strong>' +
        '  </div>' +
        '  <issue-card ng-repeat="issue in issues" issue="issue" lane="lane" on-move="onMove({ issue: issue, targetStatus: targetStatus })" on-select="onSelect({ issue: issue })"></issue-card>' +
        '</section>'
    };
  });
})();
