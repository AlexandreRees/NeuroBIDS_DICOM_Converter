%% General Parameters
% Resultfile directory
resultdir = './Results';

runs = 1;

%Stimulus parameters
fixRadius_inner = 0.15 % inner radius of the fixation spot in degrees 
fixRadius = 0.25; %fixation dot radius in degrees
fixColor = [255 0 0];
%% List of paradigms 
% List of conditions (DO NOT EDIT)
conditionNone	= 0;
conditionStim	= 1;
conditionEnd	= 2;

firstBaselineEnd = 10;
numCycles 		 = 12;
cycleStim		 = 8;
cycleBaseline	 = 10;

runParadigmFinal = [
    0 conditionNone;
    firstBaselineEnd conditionStim;
    cumsum(repmat([cycleStim;cycleBaseline],numCycles,1))+firstBaselineEnd repmat([conditionNone;conditionStim],numCycles,1)
    ];

runParadigmFinal(end,2)=conditionEnd;
runParadigmFinal(end,1)=runParadigmFinal(end,1)+0;
%% Generate stimulus that will show
% order of stimulus presentation:

stimRunIndices(:,:,1) = [
    1,2,3,4,5,6,7,8,9,10,11,12;
];

stimRunIndices(:,:,2) = [
    12,11,10,9,8,7,6,5,4,3,2,1;
];

if fMRI_number==1
    stimRunIndices(:,:,3) =[ 11     6    10    12     1     5     9     2     4     7     3     8];
elseif fMRI_number==2
    stimRunIndices(:,:,3) =[ 6     9    10     3     7     5    1    12     8     4     2     11];
elseif fMRI_number==3
    stimRunIndices(:,:,3) =[ 3     1     7     8     9     4    12    11     6     2    10     5];
elseif fMRI_number==4
    stimRunIndices(:,:,3) =[ 12     3    10     6    11     7    1     2     5     8     9     4];
elseif fMRI_number==5
    stimRunIndices(:,:,3) =[ 2     8     5     3     7    10     4     9     1     6    11    12];
elseif fMRI_number==6
    stimRunIndices(:,:,3) =[ 1     6     7     2    12     9    11     3     4     5    10     8];
end
% save stim order 
Stim_order_selected = stimRunIndices(:,:,stimOrder);
format long 
t = datestr(now,'mmmm-dd-yyyy_HH-MM-SS_AM')
save([resultdir '/' (t) '__Subject_is_' comment '__sequence_of_stimuli_for_fMRI_number_' num2str(fMRI_number) '_is_' num2str(stimRunIndices(:,:,stimOrder))],'Stim_order_selected');
save([resultdir '/fMRI_' num2str(fMRI_number)],'Stim_order_selected');

generateStimulus = @generateStim;

function stim = generateStim(paradigmNumber)
    switch paradigmNumber
       case 2
           % magno
            GratingStimulus1
            stim{1} = CheckerMoveSquare(stimParams, 2);
            GratingStimulus1
            stim{2} = CheckerFlickerSquare(stimParams, 10);
            GratingStimulus2
            stim{3} = CheckerMoveSine(stimParams, 2);
            % repeat magno
            GratingStimulus1
            stim{7} = CheckerMoveSquare(stimParams, 2);
            GratingStimulus1
            stim{8} = CheckerFlickerSquare(stimParams, 10);
            GratingStimulus2
            stim{9} = CheckerMoveSine(stimParams, 2);

            % parvo
			GratingStimulus3
			stim{4} = CheckerFlickerSquare(stimParams,2);
			GratingStimulus4
			stim{5} = CheckerMoveSquare(stimParams,2);
			GratingStimulus5
			stim{6} = CheckerFlickerSquare(stimParams,2);
            % repeat parvo
            GratingStimulus3
			stim{10} = CheckerFlickerSquare(stimParams,2);
			GratingStimulus4
			stim{11} = CheckerMoveSquare(stimParams,2);
			GratingStimulus5
			stim{12} = CheckerFlickerSquare(stimParams,2);
    end	
end