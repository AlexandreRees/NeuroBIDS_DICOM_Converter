%% run this code only once 

answer  = questdlg(sprintf([' Have you transfered the code used for the previous subejct?' ...
'\n Have you deleted the content of the Folder called "Results"? ' ...
'\n' ]), 'IMPORTANT STEP');

% Handle response
switch answer
    case 'Yes'
        disp([answer ' CONTINUE '])
    case 'No'
        warningMessage = sprintf('DO IT NOW!');
        uiwait(warndlg(warningMessage));
        return
    case 'Cancel'
        warningMessage = sprintf('DO IT NOW!');
        uiwait(warndlg(warningMessage));
        return
end

x = inputdlg('Subject Initials')
subject_initials = x{1}

runs_random = [1,4,2,5,3,6];

% save the order
runs_random_record = runs_random
save Results/runs_random runs_random

file_name_to_record = sprintf(['Results/runs_random_record_', subject_initials])
save(file_name_to_record, 'runs_random_record')

message = sprintf(['Selected sequence of runs is:   ' num2str(runs_random_record) ...
'\n'...
'\n 1 to 3 --> Right_EYE = Stimuli' ...
'\n 4 to 6--> LEFT_EYE = Stimuli' ...
'\n' ...
'\n  Write down the NUMBERS and press OK']);

uiwait(msgbox(message, 'WRITE down the numbers'));

