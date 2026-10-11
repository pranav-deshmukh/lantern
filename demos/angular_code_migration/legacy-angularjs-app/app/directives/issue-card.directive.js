(function () {
  "use strict";

  angular.module("legacyJiraBoard").directive("issueCard", function () {
    return {
      restrict: "E",
      scope: {
        issue: "=",
        lane: "=",
        onMove: "&",
        onSelect: "&"
      },
      template:
        '<article class="issue-card {{ issue.priority | lowercase }}" ng-click="onSelect({ issue: issue })">' +
        '  <p class="eyebrow">{{ issue.key }}</p>' +
        '  <h3>{{ issue.title }}</h3>' +
        '  <p>{{ issue.summary }}</p>' +
        '  <div class="issue-meta">' +
        '    <span>{{ issue.type }}</span>' +
        '    <span>{{ issue.points }} pts</span>' +
        '    <span>{{ issue.progress }}%</span>' +
        '  </div>' +
        '  <div class="card-actions">' +
        '    <button ng-if="lane.status !== \'todo\'" ng-click="$event.stopPropagation(); onMove({ issue: issue, targetStatus: \'todo\' })">Todo</button>' +
        '    <button ng-if="lane.status !== \'in-progress\'" ng-click="$event.stopPropagation(); onMove({ issue: issue, targetStatus: \'in-progress\' })">Start</button>' +
        '    <button ng-if="lane.status !== \'review\'" ng-click="$event.stopPropagation(); onMove({ issue: issue, targetStatus: \'review\' })">Review</button>' +
        '    <button ng-if="lane.status !== \'done\'" ng-click="$event.stopPropagation(); onMove({ issue: issue, targetStatus: \'done\' })">Done</button>' +
        '  </div>' +
        '</article>'
    };
  });
})();
